import matplotlib 
matplotlib.use('agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import seaborn as sns
from scipy import interp
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV, LinearRegression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import roc_curve, auc, mean_squared_error, mean_absolute_error, explained_variance_score, r2_score
from sklearn.model_selection import train_test_split
import sys
import os

sys.path.insert(1, os.path.join(sys.path[0], '../..'))
from custom_utils import create_out_dir
	


class Classifier:
	
	def __init__(self, Y_label, out_dir, base_score='gwrvis', model_type='RandomForest', 
				 use_only_base_score=True, include_vcf_extracted_features=False, regression=False, exclude_base_score=False):
				 
		self.out_dir = out_dir
		self.Y_label = Y_label
		self.regression = regression
		self.model_type = model_type
		self.include_vcf_extracted_features = include_vcf_extracted_features
		self.base_score = base_score
		self.use_only_base_score = use_only_base_score
		self.exclude_base_score = exclude_base_score

		# Initialise classifier model based on input base_score and model_type
		self.init_model()
		
		
		
	def init_model(self):
	
		print('\n-----\nRegression:', self.regression)
		print('Model:', self.model_type, '\n-----\n')
		
		rf_params = dict(n_estimators=100, max_depth=2, random_state=0)
	
		if self.model_type == 'RandomForest':
			self.model = RandomForestClassifier(**rf_params)	
		elif self.model_type == 'Logistic':
			self.model = LogisticRegression(C=1e9, solver='lbfgs', max_iter=10000)
		
		
		# Use logistic regression for all scores except for JARVIS
		if self.base_score != 'jarvis':
			self.model_type = 'Logistic'
			self.model = LogisticRegression(C=1e9, solver='lbfgs', max_iter=10000)
			
			
		
		self.score_print_name = self.base_score
		
		if self.base_score == 'gwrvis':
			self.score_print_name = 'gwRVIS'
						
		if self.base_score == 'cadd':
			self.score_print_name = self.base_score.upper()
		
		if self.base_score == 'orion':
			self.score_print_name = self.base_score.capitalize()
			
		if self.base_score == 'jarvis':
			self.base_score = 'gwrvis'
			self.score_print_name = 'JARVIS'

		
		
		
		
	
	def preprocess_data(self, df):
	
		if self.use_only_base_score:		
			df.dropna(inplace=True)
			self.feature_cols = [self.base_score]
		
		else:
			cols_to_drop = ['chr', 'start', 'end', 'genomic_class', self.Y_label, 'clinvar_annot']
	
			vcf_dependent_cols = ['common_variants', 'common_vs_all_variants_ratio', 
								  'all_variants', 'mean_ac', 'mean_af', 'bin_1', 
								  'bin_2', 'bin_3', 'bin_4', 'bin_5', 'bin_6']
			if not self.include_vcf_extracted_features:
				cols_to_drop.extend(vcf_dependent_cols)
			if self.exclude_base_score:
				cols_to_drop.append('gwrvis')
				
			self.feature_cols = [x for x in df.columns.values if x not in cols_to_drop ]
		
		print('Features:', self.feature_cols)
		print('Label:', self.Y_label)
	
		# BETA
		# Retaining only most important features (improves AUC only by +0.001)
		#self.feature_cols = ['gwrvis', 'gc_content', 'cpg', 'mut_rate', 'cpg_islands', 'H3K4me2']
			
		self.X = df[self.feature_cols].values
		self.y = df[self.Y_label].astype(int).values

		
		
		
		
	def run_classification_with_cv(self):
		
		cv = StratifiedKFold(n_splits=5)
		
		tprs = []
		aucs = []
		mean_fpr = np.linspace(0, 1, 100)

		fig, ax = plt.subplots(figsize=(10, 10))
		
		i = 0
		for train, test in cv.split(self.X, self.y):
			probas_ = self.model.fit(self.X[train], self.y[train]).predict_proba(self.X[test])
			# Compute ROC curve and area the curve
			fpr, tpr, thresholds = roc_curve(self.y[test], probas_[:, 1])
			tprs.append(interp(mean_fpr, fpr, tpr))
			tprs[-1][0] = 0.0
			roc_auc = round(auc(fpr, tpr), 3)
			aucs.append(roc_auc)
			plt.plot(fpr, tpr, lw=1, alpha=0.3,
					 label='ROC fold %d (AUC = %0.2f)' % (i, roc_auc))

			i += 1
		plt.plot([0, 1], [0, 1], linestyle='--', lw=1, color='r', label='Chance', alpha=.8)

		mean_tpr = np.mean(tprs, axis=0)
		mean_tpr[-1] = 1.0
		self.mean_auc = round(auc(mean_fpr, mean_tpr), 3)
		std_auc = np.std(aucs)
		plt.plot(mean_fpr, mean_tpr, color='b',
				 label=r'Mean ROC (AUC = %0.2f $\pm$ %0.2f)' % (self.mean_auc, std_auc),
				 lw=2, alpha=.8)

		std_tpr = np.std(tprs, axis=0)
		tprs_upper = np.minimum(mean_tpr + std_tpr, 1)
		tprs_lower = np.maximum(mean_tpr - std_tpr, 0)
		plt.fill_between(mean_fpr, tprs_lower, tprs_upper, color='grey', alpha=.2,
						 label=r'$\pm$ 1 std. dev.')

		plt.xlim([-0.05, 1.05])
		plt.ylim([-0.05, 1.05])
		plt.xlabel('False Positive Rate')
		plt.ylabel('True Positive Rate')
		plt.title(self.score_print_name + ': 5-fold Cross-Validation ROC Curve')
		plt.legend(loc="lower right")
		plt.show()
		plt.close()
		
		
		pdf_filename = self.out_dir + '/' + self.model_type + '_ROC.' + self.score_print_name + \
						'.AUC_' + str(self.mean_auc)
						
		if self.include_vcf_extracted_features:
			pdf_filename += '.incl_vcf_features'
		pdf_filename += '.pdf'
		
		fig.savefig(pdf_filename, bbox_inches='tight')
		
		
		print('Mean AUC:', self.mean_auc)
		
		
		if self.model_type == 'RandomForest':
			self.get_feature_importances()

		self.mean_tpr = mean_tpr
		self.mean_fpr = mean_fpr
		print('==============================\n\n')

				

		
	
	def get_feature_importances(self):
	
		print("\n> Feature importances:")
		if self.model_type == 'Logistic':
			importances = self.model.coef_.reshape(-1, 1)[:, 0]
		elif self.model_type == 'RandomForest':
			importances = self.model.feature_importances_
		
		
		importances_series = pd.Series(importances, index=self.feature_cols)
		importances_series.sort_values(inplace=True)
		print(importances_series)
		
		fig, ax = plt.subplots(figsize=(14, 10))
		
		importances_series.plot.bar()
		plt.show()

		pdf_filename = self.out_dir + '/RF_importance_scores.' + self.score_print_name + '.' + self.model_type

		if self.include_vcf_extracted_features:
			pdf_filename += '.incl_vcf_features'
		pdf_filename += '.pdf'
		
		fig.savefig(pdf_filename, bbox_inches='tight')