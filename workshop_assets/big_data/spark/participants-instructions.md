## Tutorial: Deploying a Spark Cluster with Docker
> [!NOTE]
> This tutorial is a foundational introduction to the `Apache Spark` Big Data platform and Virtualization. The goal is to deploy a functional Spark cluster using Docker containers for educational purposes.

### Overview
We will build a `Spark cluster` composed of two main components:

`Spark Master`: The central coordinator.

`Spark Worker`: The node that executes the data processing tasks.


## 1. Objectives & Prerequisites
### Objectives
- Part 1: Deploy a Docker container using the pre-installed Spark distribution.
- Part 2: Perform data analytics using the spark-shell.
- Part 3: Scale the cluster and submit jobs using the spark-submit script.

### Learning Outcomes
- Container Orchestration: Manage container lifecycles (download, start, stop).
- Cluster Management: Understand Spark Master/Worker architecture.
- Application Deployment: Submit jobs to a remote cluster via CLI.

### Software Requirements
- Docker & Docker Compose [1]
- Spark 3.5.0 (Local installation required for Part 3 only) [2]
- Hardware Note: Tested on Apple Silicon (Mac M1, macOS Sonoma).

## Part 1: Setting up the Spark Cluster
### Step 1: Initialize the Environment
We will use the official Spark image, which is optimized for easy deployment.

Task:

Download the official docker-compose.yml file:

```Yaml
services:
  spark:
     image: apache/spark:latest
     container_name: spark-spark-1
     environment:
       - SPARK_MODE=master
     ports:
      - "8080:8080"
      - "7077:7077"
 # Wap this in quotes to fix the "mapping" error
command: "/opt/spark/bin/spark-class org.apache.spark.deploy.master.Master"

   spark-worker:
     image: apache/spark:latest
     container_name: spark-spark-worker-1
     depends_on:
      - spark
     environment:
     - SPARK_MODE=worker
     - SPARK_MASTER_URL=spark://spark:7077
     - SPARK_WORKER_MEMORY=1G
     - SPARK_WORKER_CORES=1
     ports:
     - "8081:8081"
# Wrap this in quotes as well
command: "/opt/spark/bin/spark-class org.apache.spark.deploy.worker.Worker spark://spark:7077"
```
Alternative: Manually pull the image:

```bash
docker pull apache/spark:latest
```
> [!TIP]
> Exercise: Open the docker-compose.yml file. Can you  identify the purpose of the services, image, environment, and ports keywords?

### Step 2: Start the Cluster
Run the following commands in your terminal:

```bash
# Start in the foreground to see logs
docker compose up
```
OR: Start in background (detached mode)
```bash
docker compose up -d
Validation:
Visit the Spark Web UI at http://localhost:8080.
```
Check:

- How many Spark Workers are listed in the UI?
- Run docker ps. How many containers are currently active?

## Part 2: Data Analysis with Spark-Shell
### Step 1: Attach a Volume for Data
To analyze your own data, you must map a local folder to the container.

Open docker-compose.yml.

Add a Volumes section to the Spark service:

```YAML
services:
  spark:
    volumes:
      - type: bind
        source: .
        target: /opt/spark-data
```
Download the Bank Personal Loan dataset from Kaggle [3] into your current directory.

### Step 2: Access the Spark Shell
Get a bash shell inside the running Master container:

```bash
docker exec -it <container-id> bash
```
# Once inside the container, start the shell:
spark-shell
### Step 3: Manipulate Data
Run these Scala commands inside the spark-shell to analyze the CSV:

```scala
// Read the CSV file
val df = spark.read.format("csv").option("header","true").load("/opt/spark-data/Bank_Personal_Loan_Modelling.csv")

// View Schema
df.printSchema()

// Filter Data: Users older than 30
df.select("Age", "Income", "Family").filter("Age > 30").show()
```

## Part 3: Scaling & Job Submission
### Step 1: Scale the Cluster
To simulate a larger environment, we will scale the number of workers.

Stop existing containers: docker-compose down

Restart with three workers:

```bash
docker compose up --scale spark-worker=3
```
### Step 2: Submit a Job
The spark-submit script is the standard way to deploy applications. Ensure your local Spark bin folder is in your PATH.

```bash
spark-submit \
  --class org.apache.spark.examples.SparkPi \
  --master spark://<master-IP>:7077 \
  --deploy-mode client \
  /path/to/spark-examples_2.12-3.5.0.jar 10
```
## References
[1] [Docker Documentation ualization ](https://docs.docker.com/)

[2] [Spark Image]( https://hub.docker.com/r/spark/spark)

[3] [Kaggle Dataset: Personal Loan Modelling](https://www.kaggle.com/datasets/krantiswalke/bank-personal-loan-modelling)

[4] [Spark-Submit Guide](https://supergloo.com/spark/spark-submit/)

[5] [Docker quick start](https://spark.apache.org/docs/latest/quick-start.html)

[7] [docker builder](https://docs.docker.com/engine/reference/builder/)

[8] [Docker compose](https://docs.docker.com/compose/gettingstarted/)

[11] [pyspark](https://supergloo.com/pyspark/python-spark-cluster/#?utm_content=cmp-true)

[4] https://streaming.humix.com/contents/dnEmKDUvkLkZdeHP/1678083066/index.m3u8
