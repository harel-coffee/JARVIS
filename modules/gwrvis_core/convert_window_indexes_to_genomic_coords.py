import pandas as pd
import sys
import os

sys.path.insert(1, os.path.join(sys.path[0], '..'))
from custom_utils import create_out_dir, get_config_params

config_file = sys.argv[1]	#'config.yaml'


# read config parameters from config file and store into a dictionary
config_params = get_config_params(config_file)
print(config_params)

out_dir = create_out_dir(config_file)
print(out_dir)

win_len = config_params['win_len']

gwrvis_dir = out_dir + '/gwrvis_scores'



chroms = list(range(1,23))
#chroms.append('X')
chroms = [str(ch) for ch in chroms]

chr_start_coords_file = out_dir + '/chr_start_coords.txt'
chr_start_coords = dict()
chr_start_coords_multiple_of_winlen = dict()

with open(chr_start_coords_file, 'r') as fh:
	for line in fh:
		line = line.rstrip()
		chr, start_coord, first_window_index = line.split('\t')
		chr_start_coords[chr] = int(start_coord)		
		chr_start_coords_multiple_of_winlen[chr] = int(first_window_index) * win_len		
print(chr_start_coords)
print(chr_start_coords_multiple_of_winlen)



full_gwrvis_bed_df = pd.DataFrame()

for chr in chroms:

	cur_gwrvis_file = gwrvis_dir + '/studres.chr' + chr + '.txt'
	if not os.path.exists(cur_gwrvis_file):
		sys.exit("[Error]: " + cur_gwrvis_file + " does not exist.")

	print('Converting window indexes to genomic coordinates for chromosome', chr)
	

	def convert_win_coords(row):
		win_idx = row['win_idx']
		gwrvis = row['gwrvis']
		
		start_coord = int(win_idx) * win_len + chr_start_coords_multiple_of_winlen[chr]
		end_coord = start_coord + win_len - 1

		output_str =  'chr' + chr + ' ' + str(start_coord) + ' ' + str(end_coord) + ' ' + str(gwrvis)
		return output_str
		

	# all gwRVIS values for a single chr are contained in a single (first) line of the respective file
	with open(cur_gwrvis_file) as f:
		tmp_concat_str = f.readline()

	cur_gwrvis_array = tmp_concat_str.split()
	cur_gwrvis_df = pd.DataFrame(cur_gwrvis_array, columns=['gwrvis'])
	cur_gwrvis_df['win_idx'] = cur_gwrvis_df.index.values
	print(cur_gwrvis_df.head())
	print(cur_gwrvis_df.tail())

	tmp_out = cur_gwrvis_df.apply(convert_win_coords , axis=1)

	df = pd.DataFrame(tmp_out, columns=['tmp_out'])
	df = pd.DataFrame(df.tmp_out.str.split(' ').tolist(),
			  columns = ['chr', 'start', 'end', 'gwrvis'])
	print(df.head())


	cur_out_fh = gwrvis_dir + '/gwrvis.chr' + str(chr) + '.genomic_coords.bed'
	df.to_csv(cur_out_fh, sep='\t', index=False, header=False)


	df.reset_index(inplace=True)
	df.columns.values[0] = 'win_index'


	# copy BED file from current chromosome to the global df
	full_gwrvis_bed_df = pd.concat([full_gwrvis_bed_df, df], axis=0)
	print(full_gwrvis_bed_df.shape)


# Save full data frame into file
full_gwrvis_out_file =  gwrvis_dir + '/full_genome.all_gwrvis.bed'
full_gwrvis_bed_df.to_csv(full_gwrvis_out_file, sep='\t', index=False)
