import pandas as pd
import matplotlib.pyplot as plt

# Load the CSV file
csv_file = "RAM_drift.csv"  # Replace with the path to your CSV file
column1_name = "single_photon_chan3"  # Replace with the name of the first column
column2_name = "single_photon_chan4"  # Replace with the name of the second column

# Read the CSV file into a DataFrame
data = pd.read_csv(csv_file)

# Check if the specified columns exist
if column1_name not in data.columns or column2_name not in data.columns:
    raise ValueError(f"Columns '{column1_name}' and/or '{column2_name}' not found in the CSV file.")

# Filter out rows where both columns have values greater than 0
data = data[(data[column1_name] > 0) & (data[column2_name] > 0)]

# Group data into bins of 100 points and calculate the mean for each bin
bin_size = 300
binned_data = data.groupby(data.index // bin_size).mean()

# Calculate rolling averages
rolling_window = 300  # Define the rolling window size
rolling_avg_col1 = data[column1_name].rolling(window=rolling_window).mean()
rolling_avg_col2 = data[column2_name].rolling(window=rolling_window).mean()

# Create the first plot: Scatter plot with lines for binned data
plt.figure(figsize=(12, 10))

plt.subplot(2, 1, 1)  # First subplot
plt.plot(binned_data.index * bin_size, binned_data[column1_name], marker='o', label=column1_name, color='blue', linestyle='-')
plt.plot(binned_data.index * bin_size, binned_data[column2_name], marker='o', label=column2_name, color='orange', linestyle='-')
plt.title(f"Scatter Graph with Lines for Binned Data (Bin Size = {bin_size})")
plt.xlabel("Row Index (Start of Bin)")
plt.ylabel("Average Value")
plt.legend()
#plt.xlim(0, 60000)  # Set a manual cutoff for the x-axis

# Create the second plot: Rolling average
plt.subplot(2, 1, 2)  # Second subplot
plt.plot(data.index, rolling_avg_col1, label=f"{column1_name} (Rolling Avg)", color='blue', linestyle='-')
plt.plot(data.index, rolling_avg_col2, label=f"{column2_name} (Rolling Avg)", color='orange', linestyle='-')
plt.title(f"Rolling Average (Window Size = {rolling_window})")
plt.xlabel("Row Index")
plt.ylabel("Rolling Average Value")
plt.legend()
#plt.xlim(0, 60000)

# Adjust layout and show the plots
plt.tight_layout()
plt.show()