import matplotlib
matplotlib.use('agg') 
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from collections import Counter
import pickle
import random
import textwrap
import uuid

from scipy import interp
from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score
from sklearn.metrics import roc_curve, auc


import logging 
logging.getLogger('tensorflow').disabled = True
import sys, os 
#os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import Dense, Dropout, Activation, Flatten
from tensorflow.keras.layers import Convolution1D, MaxPooling1D
from tensorflow.keras.callbacks import ModelCheckpoint, EarlyStopping
from tensorflow.keras.optimizers import Adam


from sklearn.model_selection import StratifiedKFold, cross_val_score
from imblearn.under_sampling import RandomUnderSampler
import nn_models
from func_api_nn_models import *
from prepare_data import JarvisDataPreprocessing



os.environ['KMP_WARNINGS'] = 'off'
os.environ['CUDA_VISIBLE_DEVICES'] = '1'
#sys.path.insert(1, os.path.join(sys.path[0], '..')) 
sys.path.insert(1, os.path.join(sys.path[0], '.')) 
import custom_utils
from simple_dnn import create_feedf_dnn, train_feedf_dnn




class JarvisTraining:

	def __init__(self, config_file, include_vcf_features=False):
		
		self.config_file = config_file
		self.include_vcf_features = include_vcf_features		

		config_params = custom_utils.get_config_params(config_file)
		self.win_len = config_params['win_len']
		#self.win_len = int(config_params['win_len'] / 2)

		self.init_ouput_dirs()
		print(self.out_dir)


		jarvis_pkl_file = self.ml_data_dir + '/jarvis_data.pkl'
		if predict_on_test_set:
			jarvis_pkl_file = self.ml_data_dir + '/jarvis_data.' + str(test_indexes[0]) + '_' + str(test_indexes[1]) + '.pkl'
		self.data_dict_file = jarvis_pkl_file
		
		
		# @anchor -- REUNDANT check: already calling the prepara_data.py module prior to training
		if not os.path.exists(self.data_dict_file): 
			print("\nPreparing training data - calling JarvisDataPreprocessing object...")
			data_preprocessor = JarvisDataPreprocessing(config_file, predict_on_test_set=predict_on_test_set, test_indexes=test_indexes)
			
			# Extract raw sequences from input variant windows and combine with original feature set         
			additional_features_df, filtered_onehot_seqs = data_preprocessor.compile_feature_table_incl_raw_seqs()        
			# Merge data, transform into form appropriate for DNN training and save into file
			self.data_dict_file = data_preprocessor.transform_and_save_data(additional_features_df, filtered_onehot_seqs)         
		print(self.data_dict_file)
		



	def init_ouput_dirs(self):
		# Init output dir structure
		self.out_dir = custom_utils.create_out_dir(self.config_file)
		self.ml_data_dir = self.out_dir + '/ml_data'
		self.clinvar_feature_table_dir = self.ml_data_dir + '/clinvar_feature_tables'
		self.out_models_dir = self.ml_data_dir + '/models'

		self.raw_seq_dir = self.ml_data_dir + '/raw_seq'
		if not os.path.exists(self.raw_seq_dir):
			os.makedirs(self.raw_seq_dir)
		


	def read_data(self):

		print('Reading training data...\nFile: ', self.data_dict_file)
		
		cnt = 1
		while True:
			try:
				pkl_in = open(self.data_dict_file, 'rb')
				data_dict = pickle.load(pkl_in)
				pkl_in.close()
				break
				
			except:
				print("Failed to read " + self.data_dict_file  + " (attempt - " + str(cnt) + "). Retrying...")
				
			cnt += 1
			
		print("Successfully read: " + self.data_dict_file + "\n")
			
			
		return data_dict


	def inspect_input_data(self, data_dict):

		print('\n> Inspecting input data:')
		print('X:', data_dict['X'].shape)
		print('vcf_features:', data_dict['vcf_features'].shape)
		print('y:', data_dict['y'].shape)
		print('seqs:', data_dict['seqs'].shape)
		print('genomic_classes:', data_dict['genomic_classes'])
		print('genomic_classes:', type(data_dict['genomic_classes']))
		print('genomic_classes:', data_dict['genomic_classes'].shape)
		print('coords_df:', data_dict['coords_df'].shape)




	def subset_data_dict_by_index(self, data_dict, indexes):
	
		print('All indexes:', len(indexes))		
		for key, _ in data_dict.items():

			if key in ['X_cols', 'vcf_features_cols']:
				continue

			print('\n> Subsetting', key, ':', len(data_dict[key]))
			#print(indexes[:10])
			#print(data_dict[key][:10])

			data_dict[key] = data_dict[key][indexes]
			print('Filtered', key, ':', len(data_dict[key]))

		return data_dict



	def filter_data_by_genomic_class(self, data_dict, genomic_classes=None):
		
		print('Retaining only variants for class:', ', '.join(genomic_classes)) 

		all_class_indexes = np.array([])
		for cur_class in genomic_classes:
			cur_class_indexes = np.argwhere(data_dict['genomic_classes'] == cur_class)
			print(cur_class, ':', len(cur_class_indexes))
			all_class_indexes = np.append(all_class_indexes, cur_class_indexes)

		all_class_indexes = all_class_indexes.astype(int).tolist()
		
		filtered_data_dict = self.subset_data_dict_by_index(data_dict, all_class_indexes)
		print('filtered unique genomic_classes:', np.unique(filtered_data_dict['genomic_classes']))

		return filtered_data_dict	



	def include_vcf_features_for_prediction(self, data_dict):	
		X = np.concatenate(data_dict['X'], data_dict['vcf_features'], axis=1)
		
		return X


	
	def fix_class_imbalance(self, X, y, seqs, X_chr, pos_neg_ratio=1/1):
	
		"""
			Fix class imbalance (with over/under-sampling minority/majority class)
		"""
		
		y = np.argmax(y, axis=1)
		
		
		positive_set_size = (y == 1).sum()
		negative_set_size = (y == 0).sum()
		print('Positive / Negative size:', positive_set_size, '/', negative_set_size)

		if positive_set_size / negative_set_size < pos_neg_ratio:
			print('\n> Fixing class imbalance ...')
			print('Imbalanced sets: ', sorted(Counter(y).items()))
			rus = RandomUnderSampler(random_state=0, sampling_strategy=pos_neg_ratio)
			X, y = rus.fit_resample(X, y)
			print('Balanced sets:', sorted(Counter(y).items()))
			#print('Sampled indices:', rus.sample_indices_)
			
			print('Original X_chr:', X_chr.shape)
			X_chr = X_chr[rus.sample_indices_]
			print('Sampled X_chr:', X_chr.shape)


			if seqs is not None:
				print('Original seqs:', seqs.shape)
				seqs = seqs[rus.sample_indices_]
				print('Sampled seqs:', seqs.shape)
				

		y = tf.keras.utils.to_categorical(y)
		
		return X, y, seqs, X_chr
	
		
	
	
	def train_full_model(self, X, y, seqs, input_features, batch_size, epochs, validation_split, patience, X_len, genomic_classes):			
		"""
		    TRAIN FULL MODEL FOR JARVIS
		"""
		if input_features == 'structured':
			train_inputs = X
			patience = 10
		elif input_features == 'sequences':
			train_inputs = seqs
		elif input_features == 'both':
			train_inputs = [X, seqs]




		# > Keras functional API
		if input_features == 'structured':
			# @ Feed-forward DNN (for structured features input only)
			model = dnn_model(X_len, nn_arch=nn_arch)	
		elif input_features == 'sequences':
			# @ CNN-CNN-FC-FC (for sequence features only)
			model = sequence_model(self.win_len)
		elif input_features == 'both':
			# @ CNN-CNN-_concat_FeedfDNN_FC-FC (structured and sequence features)
			model = concat_model(X_len, nn_arch=nn_arch, win_len=self.win_len)

		optimizer = 'adam' # Adam(lr=0.0001) #'adam'
		#model.compile(loss='binary_crossentropy', optimizer=optimizer, metrics=['accuracy'])
		model.compile(loss='binary_crossentropy', optimizer=optimizer, metrics=['accuracy'])
		print(model.summary())

		# ---- Callbacks ----
		checkpoint_dir = self.ml_data_dir + '/checkpoint_cv_models'
		if not os.path.exists(checkpoint_dir):
			os.makedirs(checkpoint_dir)
		checkpoint_name = checkpoint_dir + '/jarvis.' + input_features + '_features.' + '-'.join(genomic_classes) + '.full_best_model_with_cv.' + str(uuid.uuid4().hex) + '.hdf5'
		checkpointer = ModelCheckpoint(checkpoint_name, monitor='val_loss', verbose=verbose, 
					       save_weights_only=False, save_best_only=True, mode='auto')
		patience = patience
		earlystopper = EarlyStopping(monitor='val_loss', patience=patience, verbose=verbose)
		# -------------------

		history = model.fit(train_inputs, y, batch_size=batch_size, epochs=epochs, 
			  shuffle=True,
			  validation_split=validation_split, 
			  callbacks=[checkpointer, earlystopper], 
			  verbose=verbose)
		#self.plot_history(history, fold_id='full_model')

		model_out_file = self.out_models_dir + '/' + '_'.join(genomic_classes) + '/JARVIS-' + input_features + '.model'
		#with open(model_out_file, 'wb') as fh:
		#	pickle.dump(model, fh)
		model.save(model_out_file)

		print("Saved full model into:", model_out_file, '\n')
		
		


		
	def get_fold_indexes_by_chrom_split(self, X_chr, kfold=5):
		"""
		    Get indexes of validation sets, stratified by chromosome
		"""

		all_chroms = list(range(1, 23))
		chroms_in_val_set = []
		indexes_in_test_set = []
		indexes_in_train_set = []

		kfold = 5
		for k in range(kfold):
			print('fold:', k+1)
			tmp_chroms_in_val_set = random.sample(all_chroms, 3)
			all_chroms = list(set(all_chroms) - set(tmp_chroms_in_val_set))

			chroms_in_val_set.append(tmp_chroms_in_val_set)

			# find indexes of data points that belong to certain chromosomes
			tmp_indexes_in_test_set = []
			for chrom in tmp_chroms_in_val_set:
				cur_indexes = [i for i,x in enumerate(X_chr) if x == chrom]
				tmp_indexes_in_test_set.extend(cur_indexes)

			print(len(tmp_indexes_in_test_set))

			# get complement of indexes for train set
			tmp_train_indexes = set(range(len(X_chr))) - set(tmp_indexes_in_test_set)
			#print('full list:', len(X_chr))
			#print('train size:', len(tmp_train_indexes))
			#print('test size:', len(tmp_indexes_in_test_set))


			indexes_in_train_set.append(tmp_train_indexes)
			indexes_in_test_set.append(tmp_indexes_in_test_set)

		return indexes_in_train_set, indexes_in_test_set




	def convert_onehot_to_raw_seq(self, onehot_seq):
		#print(onehot_seq)
		onehot_index_to_nt = {0: 'A', 3: 'T', 2: 'G', 1: 'C'}
		raw_seq = ''
	
		cnt = 0
		for cur_nt in onehot_seq:
			#print(cur_nt)

			t = np.where(cur_nt == 1)[0][0]
			#print(t)
			#print(onehot_index_to_nt[t])
			raw_seq += onehot_index_to_nt[t]

		return raw_seq






	def train_with_cv(self, data_dict, include_vcf_features, genomic_classes,
			  n_splits=5, batch_size=16, epochs=40, validation_split=0, patience=10,
			  use_multiprocessing=True, verbose=0, input_features='structured', cv_repeats=5):
		""" 
			Arg 'input_features' may take 1 of 3 possible values:
			- stuctured: using only structured features as input
			- sequence: using only sequence features as input
			- both: using both structured and sequence features as inputs
		"""
		


		#if input_features != 'structured':
		#	verbose = 1

		# 'X'
		if self.include_vcf_features:
			X = self.include_vcf_features_for_prediction(data_dict)
		else:
			X = data_dict['X'].copy()
		print('- X features:', X.shape)
		
		# 'y'
		y = data_dict['y'].copy()
		
		# 'seqs'
		if input_features != 'structured':
			seqs = data_dict['seqs'].copy()
		else:
			seqs = None
			
			
			
			


		
		X_chr = data_dict['coords_df'][:, 0]
		X, y, seqs, X_chr = self.fix_class_imbalance(X, y, seqs, X_chr)


		# Get indexes of validation sets, stratified by chromosome (to be used in A-hoc analysis later on)
		self.indexes_in_train_set, self.indexes_in_test_set = self.get_fold_indexes_by_chrom_split(X_chr)




		
		# ------ Custom NN settings for CCDS and introns ------
		if '_'.join(genomic_classes) == 'ccds':
			cv_repeats = 1
			n_splits = 10
			#batch_size = 1024
			patience = 2

		if '_'.join(genomic_classes) == 'intron':
			cv_repeats = 2
			n_splits = 10
			#batch_size = 128
			patience = 5
		print("Batch size:", batch_size)
		# -----------------------------------------------------

	
		tprs = [] 
		aucs = [] 
		metrics_list = []

		# output dir for test_label/test_probas_ results (input for DeLong's test)
		delong_test_dir = self.ml_data_dir + '/clinvar-out/delong_test'
		if not os.path.exists(delong_test_dir):
			os.makedirs(delong_test_dir)	
		y_label_lists = []
		y_proba_lists = []


		mean_fpr = np.linspace(0, 1, 100)  		
		fig, ax = plt.subplots(figsize=(10, 10))
	
		skf = StratifiedKFold(n_splits=n_splits, shuffle=True)


		cv_data_dict = {}
		fixed_cv_batches_file = self.ml_data_dir + '/fixed_cv_batches.' + '_'.join(genomic_classes) + '.pkl'
		# load CV batches from pickle file
		if use_fixed_cv_batches:
			print("\nLoading fixed CV batches...")
			with open(fixed_cv_batches_file, 'rb') as handle:
				cv_data_dict = pickle.load(handle)



		# NEW Remove TSS_distance
		#X = X[:, :-1]  

		# Remove only phastCons_primate
		#X = np.delete(X, -2, axis=1)

		
		# @anchor
		# NEW Remove TSS_distance and phastCons_primate
		X = X[:, :-2]  
		
		# remove gwrvis
		#X = X[:, 1:]


		y_col = np.array(np.argmax(y, axis=1))
		patho_indexes = np.where(y_col == 1)[0]
		benign_indexes = np.where(y_col == 0)[0]




		# Save training set raw sequences for motif analysis
		if input_features != 'structured':
			patho_raw_seqs = []
			for p_i in patho_indexes:
				cur_onehot_seq = seqs[p_i]
				cur_raw_seq = self.convert_onehot_to_raw_seq(cur_onehot_seq)
			
				patho_raw_seqs.append(cur_raw_seq)

			benign_raw_seqs = []
			for b_i in benign_indexes:
				cur_onehot_seq = seqs[b_i]
				cur_raw_seq = self.convert_onehot_to_raw_seq(cur_onehot_seq)
			
				benign_raw_seqs.append(cur_raw_seq)

			
			# Write sequences to files (in 500bp chunks)
			seq_chunk_len = 500
			with open(self.raw_seq_dir + '/Training_set.pathogenic_variant_sequences.txt', 'w') as fh:
				for p_seq in patho_raw_seqs:
					for subseq in textwrap.wrap(p_seq, seq_chunk_len):
						fh.write(subseq + '\n')

			with open(self.raw_seq_dir + '/Training_set.benign_variant_sequences.txt', 'w') as fh:
				for b_seq in benign_raw_seqs:
					for subseq in textwrap.wrap(b_seq, seq_chunk_len):
						fh.write(subseq + '\n')


		

			
			
		if train_full_model:
			self.train_full_model(X, y, seqs, input_features, batch_size, epochs, validation_split, patience, X.shape[1], genomic_classes)
			
		elif train_with_cv:
			

			# n-repeated CV
			for n in range(cv_repeats):
				print('\n>> CV - Repeat:', str(n+1))

				fold = 0
				for train_index, test_index in skf.split(X, np.argmax(y, axis=1)):
				# ===== Ad-hoc analysis: Get indexes of validation sets, stratified by chromosome =====
				#for k in range(len(self.indexes_in_test_set)):
					#train_index = list(self.indexes_in_train_set[k])
					#test_index = list(self.indexes_in_test_set[k])

					if use_fixed_cv_batches:
						train_index, test_index = cv_data_dict[fold]
					else:
						cv_data_dict[fold] = [train_index, test_index]




					y_train, y_test = y[train_index], y[test_index]
					X_train, X_test = X[train_index], X[test_index]
					print('X_train:', X_train.shape)
					print('y_train:', y_train.shape)
					print('X_test:', X_test.shape)
					print('y_test:', y_test.shape)

					if input_features != 'structured':
						seqs_train, seqs_test = seqs[train_index], seqs[test_index]
						print('seqs_train:', seqs_train.shape)
						print('seqs_test:', seqs_test.shape)
					
					if input_features == 'structured':
						train_inputs = X_train
						test_inputs = X_test
					elif input_features == 'sequences':
						train_inputs = seqs_train
						test_inputs = seqs_test
					elif input_features == 'both':
						train_inputs = [X_train, seqs_train]
						test_inputs = [X_test, seqs_test]
					#"""
				
	
						
					
		
					if use_pathogenicity_trained_model:
						
						model_out_file = self.out_models_dir + '/' + '_'.join(genomic_classes) + '/JARVIS-' + input_features + '.model'
						print("\n>> Loading PATHOGENICITY-trained model from file:", model_out_file)
					
						model = load_model(model_out_file)
						print("Loaded saved model:", model_out_file)

					
					else:
						# -- Create new/clean model instance for each fold
						# > Keras functional API
						if input_features == 'structured':
							# @ Feed-forward DNN (for structured features input only)
							model = dnn_model(X.shape[1], nn_arch=nn_arch)	
						elif input_features == 'sequences':
							# @ CNN-CNN-FC-FC (for sequence features only)
							#model = func_api_nn_models.cnn2_fc2(self.win_len)
							model = sequence_model(self.win_len)
						elif input_features == 'both':
							# @ CNN-CNN-_concat_FeedfDNN_FC-FC (structured and sequence features)
							model = concat_model(X.shape[1], nn_arch=nn_arch, win_len=self.win_len)
						model.compile(loss='binary_crossentropy', optimizer='adam', metrics=['accuracy'])
						print(model.summary())


						# ---- Callbacks ----
						checkpoint_dir = self.ml_data_dir + '/checkpoint_cv_models'
						if not os.path.exists(checkpoint_dir):
							os.makedirs(checkpoint_dir)
						checkpoint_name = checkpoint_dir + '/jarvis.' + input_features + '_features.' + '-'.join(genomic_classes) + '.best_model_with_cv.hdf5'
						checkpointer = ModelCheckpoint(checkpoint_name, monitor='val_loss', verbose=verbose, save_best_only=True, mode='auto')
						patience = 10
						#if input_features == 'structured':
						#	patience = 20  # may lead to over-fitting
						earlystopper = EarlyStopping(monitor='val_loss', patience=patience, verbose=verbose)
						# -------------------

						#print('train_input:', train_inputs)
						#print('y_train:', y_train)



						history = model.fit(train_inputs, y_train, batch_size=batch_size, epochs=epochs, 
							  shuffle=True,
							  validation_split=validation_split, 
							  callbacks=[checkpointer, earlystopper], 
							  verbose=verbose)
						#self.plot_history(history, fold_id=(fold+1))


					


					# - Get prediction probabilities per class 				
					#probas_ = model.predict_proba(X_test)
					probas_ = model.predict(test_inputs)  # for Keras functional API
					
					y_label_lists.append(np.argmax(y_test, axis=1))
					y_proba_lists.append(probas_[:, 1])					

					
					# Compute ROC curve and area the curve 				
					fpr, tpr, thresholds = roc_curve(np.argmax(y_test, axis=1), probas_[:, 1])

					tprs.append(interp(mean_fpr, fpr, tpr)) 
					tprs[-1][0] = 0.0 
					roc_auc = round(auc(fpr, tpr), 3) 	
					print('Fold-', str(fold+1), ' - AUC: ', roc_auc, '\n')
					aucs.append(roc_auc)
					plt.plot(fpr, tpr, lw=1, alpha=0.3, label='ROC fold %d (AUC = %0.3f)' % (fold, roc_auc))


					# Evaluate predictions on test and get performance metrics
					metrics = self.test_and_evaluate_model(probas_, y_test)
					metrics['auc'] = roc_auc
					metrics_list.append(metrics)
					
					fold += 1
					

			#'_'.join(genomic_classes)
			# Save X-test and proba results across all folds - Input to DeLong's test
			with open(delong_test_dir + '/JARVIS-' + input_features + '.' + '_'.join(genomic_classes) + '.y_label_lists.txt', 'w') as fh:
				for tmp_list in y_label_lists:
					fh.write(', '.join([str(i) for i in tmp_list]) + '\n')

			with open(delong_test_dir + '/JARVIS-' + input_features + '.' + '_'.join(genomic_classes) + '.y_proba_lists.txt', 'w') as fh:
				for tmp_list in y_proba_lists:
					fh.write(', '.join([str(i) for i in tmp_list]) + '\n')	


					
			# Save CV batches to a pickle file
			if not use_fixed_cv_batches:
				print("\nSaving CV batches to a pickle file...")
				with open(fixed_cv_batches_file, 'wb') as handle:
					pickle.dump(cv_data_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
		


			plt.plot([0, 1], [0, 1], linestyle='--', lw=1, color='r', label='Chance', alpha=.8)
			
			
			mean_tpr = np.mean(tprs, axis=0)
			mean_tpr[-1] = 1.0
			self.mean_auc = round(auc(mean_fpr, mean_tpr), 3)
			std_auc = np.std(aucs)
			plt.plot(mean_fpr, mean_tpr, color='b',
					 label=r'Mean ROC (AUC = %0.3f $\pm$ %0.2f)' % (self.mean_auc, std_auc),
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
			plt.title('[' + ','.join(genomic_classes) + ']: ' + str(n_splits) + '-fold Cross-Validation ROC Curve')
			plt.legend(loc="lower right")
			#plt.show()
			#plt.close()
			
			
			#pdf_filename = self.out_dir + '/Jarvis.' + input_features + '_features.' + '-'.join(genomic_classes) + '_ROC' + '.AUC_' + str(self.mean_auc)
			pdf_filename = self.out_dir + '/Jarvis.' + input_features + '_features.' + '-'.join(genomic_classes) 
			if include_vcf_features:
				pdf_filename += '.incl_vcf_features'
			pdf_filename += '.pdf'
			
			fig.savefig(pdf_filename, bbox_inches='tight')
			
			print('Mean AUC:', self.mean_auc)
			self.metrics_list = metrics_list
			print("\nMetrics: ", metrics_list)

		
		
		

	def plot_history(self, history, fold_id=0):

		fig, ax = plt.subplots(figsize=(15, 15))

		plt.plot(history.history['loss'], label='train')
		plt.plot(history.history['val_loss'], label='validation')
		plt.title('Model loss')
		plt.ylabel('loss')
		plt.xlabel('epoch')
		plt.legend()
		
		history_out_file = self.ml_data_dir + '/jarvis.model_loss_history.Fold-' + str(fold_id) + '.pdf'
		fig.savefig(history_out_file, bbox_inches='tight')
		
		print('Model training history saved into:', history_out_file)
		
		
		
		
	def get_metrics(self, test_flat, preds_flat, verbose=0):
	
		accuracy = accuracy_score(test_flat, preds_flat)
		confus_mat =  confusion_matrix(test_flat, preds_flat)

			
		TN, FP, FN, TP = confus_mat.ravel()	

		try:
			sensitivity = TP / (TP + FN)
		except:
			sensitivity = 'NA'
		
		try:	
			precision = TP / (TP + FP)
		except:
			precision = 'NA'
		
		try:
			specificity = TN / (TN + FP)
		except:
			specificity = 'NA'
		

		if verbose:
			print('> Confusion matrix:\n', confusion_matrix(test_flat, preds_flat))		
			print('TN:', TN, '\nFP:', FP, '\nFN:', FN, '\nTP:', TP)
			
			print('\n> Accuracy:', accuracy_score(test_flat, preds_flat))
			print('> Sensitivity:', sensitivity)
			print('> Precision:', precision)
			print('> Specificity:', specificity)
		
		metrics = {'accuracy': accuracy, 'sensitivity': sensitivity, 'precision': precision, 'specificity': specificity}

		return metrics
		

			  
	def test_and_evaluate_model(self, y_probas, y_test):
		
		y_pred_flat = np.argmax(y_probas, axis=1)
		#print(y_probas)
		#print(y_pred_flat)
		
		y_test_flat = np.argmax(y_test, axis=1)
		print('y_test:', y_test_flat)
		print('y_pred:', y_pred_flat)
		
		metrics = self.get_metrics(y_test_flat, y_pred_flat)
		
		return metrics




def check_and_save_performance_metrics(metrics_list, genomic_classes, clinvar_feature_table_dir, input_features):

	score = 'jarvis-' + input_features
	
	print('\n>', score)
	#print('Metrics:', metrics)	
	
	for metric in metrics_list[0].keys():
		cur_metric_list = []
		
		for sublist in metrics_list:
			cur_metric_list.append(sublist[metric])
			
			cur_metric_list = [x if x != 'NA' else 0.5 for x in cur_metric_list]
			cur_metric_list = [x if not np.isnan(x) else 0.5 for x in cur_metric_list]
			
			
		#print(cur_metric_list)
		print('Avg.', metric, ':', np.mean(cur_metric_list))

		
	metrics_out_file = clinvar_feature_table_dir + '/jarvis_performance_metrics.' + input_features + '.' + '_'.join(genomic_classes) + '.pkl'
	with open(metrics_out_file, 'wb') as handle:
		pickle.dump(metrics_list, handle, protocol=pickle.HIGHEST_PROTOCOL)
		
	print('Metrics saved at:', metrics_out_file)
	
	
	


if __name__ == '__main__':

	print('Sys.argv in train_nn_model.py:', sys.argv)

	config_file = sys.argv[1]
	input_features = sys.argv[2]
	genomic_classes = sys.argv[3] # comma-separated
	genomic_classes = genomic_classes.split(',')	
	use_fixed_cv_batches = bool(int(sys.argv[4]))
	cv_repeats = int(sys.argv[5])
	include_vcf_features = False
	test_indexes = []

	# ----------------------
	train_with_cv = True    	# True: get generalised performance with cross-validation
	train_full_model = False  	# True: train full model (to later use on an unseen test set)


	
	
	# -- Compatible only with: train_with_cv = True
	# *************************************
	use_pathogenicity_trained_model=False
	use_conservation_trained_model=False
	# *************************************
	
	run_params = custom_utils.get_config_params(config_file)
	predict_on_test_set = bool(run_params['predict_on_test_set'])

	
	# sanity check
	if train_full_model:
		train_with_cv = False
		use_fixed_cv_batches = False
		
	if use_pathogenicity_trained_model or use_conservation_trained_model:
		train_with_cv = True
		train_full_model = False
		
	if predict_on_test_set:
		train_with_cv = False
		train_full_model = False
		if not test_indexes:
			sys.exit("[Error] - no test_indexes have been provided. Please retry e.g. with test_indexes = [0, 100000]")
	# ----------------------

	

	jarvis_trainer = JarvisTraining(config_file, include_vcf_features)


	# Read train, validation, test data
	data_dict = jarvis_trainer.read_data()

	# Print input data shapes for sanity check check for consistency
	jarvis_trainer.inspect_input_data(data_dict)


	# Filter data by genomic class
	if not predict_on_test_set:
		filtered_data_dict = jarvis_trainer.filter_data_by_genomic_class(data_dict, genomic_classes)
		print(filtered_data_dict)
	
		print('Data dict after filtering by genomic classes (:')
		jarvis_trainer.inspect_input_data(filtered_data_dict)
	else:
		filtered_data_dict = data_dict
		



	# [Deprecated] Train using only structured features (i.e. without raw sequence data)	
	#model = create_feedf_dnn(filtered_data_dict['X'].shape[1], nn_arch=[32, 32]) 
	# ===== First test run - (only train set, without test set or CV) ==========
	#if False:
	#	history = train_feedf_dnn(model, filtered_data_dict, include_vcf_features)
	#	jarvis_trainer.plot_history(history)
	# ==========================================================================
	
	
	# DNN
	nn_arch = [128, 128] # [64, 128, 256]
	dnn_model = feedf_dnn
	sequence_model = cnn2_fc2 #default: cnn2_fc2
	#sequence_model = cnn2_brnn1 
	concat_model = cnn2_concat_dnn_fc2

	verbose=1
	jarvis_trainer.train_with_cv(filtered_data_dict, include_vcf_features, genomic_classes, 
				     input_features=input_features, verbose=verbose, cv_repeats=cv_repeats)
					 
					 
	if train_with_cv:
		check_and_save_performance_metrics(jarvis_trainer.metrics_list, genomic_classes, jarvis_trainer.clinvar_feature_table_dir, input_features)

