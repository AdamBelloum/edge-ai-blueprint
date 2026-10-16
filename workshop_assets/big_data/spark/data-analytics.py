from pyspark.sql import SparkSession

# Initialize the Spark Session
spark = SparkSession.builder \
    .appName("BankLoanAnalysis") \
    .getOrCreate()

# Path to the data inside the container
file_path = "/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv"

# 1. Read the CSV
print("\n--- Reading Data ---")
df = spark.read.format("csv") \
    .option("header", "true") \
    .option("inferSchema", "true") \
    .load(file_path)

# 2. Show the Schema
print("\n--- Data Schema ---")
df.printSchema()

# 3. Perform the analysis
print("\n--- Filtering: Age > 30 ---")
result_df = df.select("Age", "Income", "Family").filter(df.Age > 30)

# 4. Show the first 10 results
result_df.show(10)

# 5. Save the results in the workshop outputs directory
print("\n--- Saving Results ---")
result_df.write.mode("overwrite").csv("/opt/spark-data/outputs/filtered_results")

# Stop the session
spark.stop()
