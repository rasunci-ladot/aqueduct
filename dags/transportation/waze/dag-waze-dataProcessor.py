# store_data_file.py - Process JSON files from AWS S3 to PostgreSQL Database
# forked from Joinville Smart Mobility Project and Louisville WazeCCPProcessor
# modified by Bryan.Blackford@lacity.org for City of Los Angeles CCP

import hashlib
import json
import logging
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd
from airflow import DAG
from airflow.hooks.postgres_hook import PostgresHook
from airflow.hooks.S3_hook import S3Hook
from airflow.models import Variable  # db schema and s3 bucket names stored in Variables
from airflow.operators.python_operator import PythonOperator
from pandas.io.json import json_normalize
from sqlalchemy import MetaData, create_engine, exc, select
from sqlalchemy.sql import and_
from sqlalchemy.types import JSON as typeJSON

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2018, 12, 3),
    "email": ["hunter.owens@lacity.org", "bryan.blackford@lacity.org"],
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 1
    # 'retry_delay': timedelta(minutes=5),
    # 'queue': 'bash_queue',
    # 'pool': 'backfill',
    # 'priority_weight': 10,
    # 'end_date': datetime(2016, 1, 1),
}

dag = DAG(
    "waze-s3-to-sql",
    description="DAG for moving Waze data from S3 to RDS",
    catchup=False,
    default_args=default_args,
    schedule_interval="*/1 * * * *",
    concurrency=3,
    max_active_runs=3,
)  # "@hourly") # *****=run every minute


def s3keyCheck():
    logging.info("s3keyCheck called")
    print("s3keyCheck")
    bucket_source_name = Variable.get("waze_s3_bucket_source")
    hook = S3Hook(aws_conn_id="s3_conn")
    if hook.check_for_wildcard_key(wildcard_key="*", bucket_name=bucket_source_name):
        logging.info("wildcard found key")
        return True
    else:
        logging.info("no key found")
        return False


def logTest():
    logging.info("logTest called")


def connect_database(connection_id):
    logging.info("connect_database called")
    dbhook = PostgresHook(postgres_conn_id=connection_id)
    logging.info("got hook")
    pgconn = dbhook.get_connection(conn_id=connection_id)
    logging.info("got connection")
    # 	DATABASE = database_dict
    # 	db_url = URL(**DATABASE)
    db_url = "postgresql://{c.login}:{c.password}@{c.host}:{c.port}/{c.schema}".format(
        c=pgconn
    )
    # logging.info ("url: "+db_url)
    engine = create_engine(db_url)
    meta = MetaData()
    meta.bind = engine

    return meta


def tab_raw_data(s3_key_obj):
    # read data file
    # doc = open(datafile_s3_key) # old local file method
    # get file from S3
    # obj = client.get_object(Bucket=bucket_source_name,Key=datafile_s3_key)
    records = json.loads(s3_key_obj.get()["Body"].read())  # doc)
    raw_data = json_normalize(records)

    # clean date fields
    raw_data["startTime"] = pd.to_datetime(raw_data["startTime"].str[:-4])
    raw_data["endTime"] = pd.to_datetime(raw_data["endTime"].str[:-4])
    raw_data["startTime"] = raw_data["startTime"].astype(pd.Timestamp)
    raw_data["endTime"] = raw_data["endTime"].astype(pd.Timestamp)

    # get creation time
    raw_data["date_created"] = pd.to_datetime("today")

    # during creation time, date_updated equals date_created
    raw_data["date_updated"] = raw_data["date_created"]

    # get_file_name
    raw_data["file_name"] = s3_key_obj.key  # datafile_s3_key

    # get AJI hash
    aji_list = [
        json.dumps(raw_data["alerts"].iloc[0], sort_keys=True)
        if "alerts" in raw_data
        else "",
        json.dumps(raw_data["jams"].iloc[0], sort_keys=True)
        if "jams" in raw_data
        else "",
        json.dumps(raw_data["irregularities"].iloc[0], sort_keys=True)
        if "irregularities" in raw_data
        else "",
    ]
    aji_string = "".join(aji_list)
    raw_data["json_hash"] = hashlib.md5(aji_string.encode()).hexdigest()

    return raw_data


def tab_jams(raw_data):
    if "jams" not in raw_data:
        # print("No jams in this data file.")
        return

    df_jams = json_normalize(raw_data["jams"].iloc[0])
    col_dict = {
        "blockingAlertUuid": "blocking_alert_id",
        "startNode": "start_node",
        "endNode": "end_node",
        "pubMillis": "pub_millis",
        "roadType": "road_type",
        "speedKMH": "speed_kmh",
        "turnType": "turn_type",
    }

    other_cols = [
        "city",
        "country",
        "delay",
        "length",
        "uuid",
        "street",
        "level",
        "line",
        "type",
        "speed",
        "id",
    ]  # segments

    df_jams.rename(columns=col_dict, inplace=True)
    col_list = list(col_dict.values())
    col_list = col_list + other_cols
    all_columns = pd.DataFrame(np.nan, index=[0], columns=col_list)
    df_jams, _ = df_jams.align(all_columns, axis=1)
    df_jams = df_jams[col_list]
    df_jams["pub_utc_date"] = pd.to_datetime(df_jams["pub_millis"], unit="ms")
    # id_string = str(df_jams["pub_millis"])+str(raw_data["json_hash"])
    # print(id_string)
    # df_jams["id"] = id_string;
    return df_jams


def tab_irregularities(raw_data):
    if "irregularities" not in raw_data:
        # print("No irregularities in this data file.")
        return

    df_irregs = json_normalize(raw_data["irregularities"].iloc[0])
    col_dict = {
        "detectionDateMillis": "detection_date_millis",
        "detectionDate": "detection_date",
        "updateDateMillis": "update_date_millis",
        "updateDate": "update_date",
        "regularSpeed": "regular_speed",
        "delaySeconds": "delay_seconds",
        "jamLevel": "jam_level",
        "driversCount": "drivers_count",
        "alertsCount": "alerts_count",
        "nThumbsUp": "n_thumbs_up",
        "nComments": "n_comments",
        "nImages": "n_images",
        "endNode": "end_node",
        "startNode": "start_node",
        "highway": "is_highway",
    }

    other_cols = [
        "street",
        "city",
        "country",
        "speed",
        "seconds",
        "length",
        "trend",
        "type",
        "severity",
        "line",
        "id",
    ]

    df_irregs.rename(columns=col_dict, inplace=True)
    col_list = list(col_dict.values())
    col_list = col_list + other_cols
    all_columns = pd.DataFrame(np.nan, index=[0], columns=col_list)
    df_irregs, _ = df_irregs.align(all_columns, axis=1)
    df_irregs = df_irregs[col_list]
    df_irregs["detection_utc_date"] = pd.to_datetime(
        df_irregs["detection_date_millis"], unit="ms"
    )
    df_irregs["update_utc_date"] = pd.to_datetime(
        df_irregs["update_date_millis"], unit="ms"
    )

    return df_irregs


def tab_alerts(raw_data):
    if "alerts" not in raw_data:
        # print("No alerts in this data file.")
        return

    df_alerts = json_normalize(raw_data["alerts"].iloc[0])
    df_alerts["location"] = df_alerts.apply(
        lambda row: {"x": row["location.x"], "y": row["location.y"]}, axis=1
    )

    col_dict = {
        "pubMillis": "pub_millis",
        "roadType": "road_type",
        "reportDescription": "report_description",
        "reportRating": "report_rating",
        "nThumbsUp": "thumbs_up",
        "jamUuid": "jam_uuid",
        "reportByMunicipalityUser": "report_by_municipality_user",
        "uuid": "id",
    }

    other_cols = [
        "uuid",
        "street",
        "city",
        "country",
        "location",
        "magvar",
        "reliability",
        "type",
        "subtype",
        "confidence",
    ]

    df_alerts.rename(columns=col_dict, inplace=True)
    col_list = list(col_dict.values())
    col_list = col_list + other_cols
    all_columns = pd.DataFrame(np.nan, index=[0], columns=col_list)
    df_alerts, _ = df_alerts.align(all_columns, axis=1)
    df_alerts = df_alerts[col_list]
    df_alerts["pub_utc_date"] = pd.to_datetime(df_alerts["pub_millis"], unit="ms")

    return df_alerts


def processJSONtoDB(**kwargs):
    logging.info("processJSONtoDB called")
    # get schema name from airflow variables
    schemaName = Variable.get("waze_db_schema")

    logging.info("Connecting to database. schema=" + schemaName)
    meta = connect_database("postgres_default")  # "aws_postgres_datalake")

    # Store data_file in database
    col_dict = {
        "startTimeMillis": "start_time_millis",
        "endTimeMillis": "end_time_millis",
        "startTime": "start_time",
        "endTime": "end_time",
        "date_created": "date_created",
        "date_updated": "date_updated",
        "file_name": "file_name",
        "json_hash": "json_hash",
    }

    # get a hook to the S3 via airflow
    hook = S3Hook(aws_conn_id="s3_conn")  # "aws_s3_waze_unprocessed")
    logging.info("Got S3 Hook")

    # get bucket names and bucket for moving files from queued to processed
    bucket_processed_name = Variable.get("waze_s3_bucket_processed")
    bucket_source_name = Variable.get("waze_s3_bucket_source")
    # bucket_source = s3.Bucket(bucket_source_name)
    bucket_processed = hook.get_bucket(bucket_processed_name)
    # files processed per run
    process_files_per_run = int(Variable.get("waze_process_files_per_run"))

    # key = hook.get_wildcard_key(wildcard_key="*",bucket_name=bucket_source_name)
    # print ("Got a key from S3 bucket:")
    # print (key.key)

    # s3 = boto3.resource('s3')
    # client = boto3.client('s3')

    # keeping track
    count = 0

    # loop through all keys (files) in source bucket
    # for key in bucket_source.objects.all(): # a list of ObjectSummary

    startTime = time.time()  # datetime.now().time()

    keylist = hook.list_keys(bucket_name=bucket_source_name, delimiter="/")
    # print ("Got list of keys:")
    # for keyTest in keylist:
    # 	print (keyTest)

    for key in keylist:
        # only process files in 'root' of bucket with json extension
        if "/" not in key and key.endswith(".json"):
            logging.info("Attempting to process key: " + key)
            logging.info("Getting key from S3")
            try:
                keyObj = hook.get_key(key, bucket_name=bucket_source_name)
            except Exception as e:
                logging.warning(
                    "S3 Key not found (pulled by another thread perhaps). "
                    "Skipping file."
                )
                print("Error getting key:{0}".format(e))
                continue

            logging.info("Getting meta data from file")
            raw_data = tab_raw_data(keyObj)  # .key) #filepath.name)

            raw_data_tosql = raw_data.rename(columns=col_dict)
            raw_data_tosql = raw_data_tosql[list(col_dict.values())]
            try:
                raw_data_tosql.to_sql(
                    name="data_files",
                    schema=schemaName,
                    con=meta.bind,
                    if_exists="append",
                    index=False,
                )
            except exc.IntegrityError as e:
                logging.warning(
                    "Data file is already stored in the relational database. "
                    "Skipping file."
                )
                print("Error:{0}".format(e))
                print("Err: ", sys.exc_info()[0])
                # return
                continue

            # sys.exit()

            # Introspect data_file table
            meta.reflect(schema=schemaName)
            data_files = meta.tables[schemaName + ".data_files"]
            datafile_result = (
                select([data_files.c.id])
                .where(
                    and_(
                        data_files.c.file_name == raw_data["file_name"].iloc[0],
                        data_files.c.json_hash == raw_data["json_hash"].iloc[0],
                    )
                )
                .execute()
                .fetchall()
            )
            if len(datafile_result) > 1:
                raise Exception("There should be only one result")

            datafile_id = datafile_result[0][0]
            logging.info("datafile id:")
            logging.info(datafile_result)

            # Store jams in database
            jams_tosql = tab_jams(raw_data)
            if jams_tosql is not None:
                jams_tosql["datafile_id"] = datafile_id
                jams_tosql.to_sql(
                    name="jams",
                    schema=schemaName,
                    con=meta.bind,
                    if_exists="append",
                    index=False,
                    dtype={"line": typeJSON},
                )

            # Store alerts in database
            alerts_tosql = tab_alerts(raw_data)
            if alerts_tosql is not None:
                alerts_tosql["datafile_id"] = datafile_id
                alerts_tosql.to_sql(
                    name="alerts",
                    schema=schemaName,
                    con=meta.bind,
                    if_exists="append",
                    index=False,
                    dtype={"location": typeJSON},
                )

            # Store irregularities in databse
            irregs_tosql = tab_irregularities(raw_data)
            if irregs_tosql is not None:
                irregs_tosql["datafile_id"] = datafile_id
                irregs_tosql.to_sql(
                    name="irregularities",
                    schema=schemaName,
                    con=meta.bind,
                    if_exists="append",
                    index=False,
                    dtype={"line": typeJSON},
                )

            # finished processing file
            print("File added to database! ")
            # store file info before deleting key
            keymb = keyObj.content_length / (1024 * 1024)
            # processedKeys.append(key)

            # move file from 'test' queue bucket to processed bucket
            copy_source = {"Bucket": bucket_source_name, "Key": key}
            bucket_processed.copy(copy_source, key)
            logging.info(
                "copied "
                + key
                + " from "
                + bucket_source_name
                + " to "
                + bucket_processed_name
            )

            # delete file from 'test' queue bucket
            # hook.delete_objects(bucket=bucket_source_name,keys=key) # airflow 1.11?
            keyObj = hook.get_key(key, bucket_name=bucket_source_name)
            keyObj.delete()
            logging.info("Deleted " + key + " from " + bucket_source_name)

            # Time to download file from S3, process, store in RDS, bucket copy
            processDoneTime = time.time()
            elapsed = processDoneTime - startTime
            mbps = keymb / elapsed
            print(
                "Processing time: %(elapsed)0.2f seconds for %(keysize)0.1f megabytes. "
                "MB/s: %(mbps)0.2f"
                % {"elapsed": elapsed, "keysize": keymb, "mbps": mbps}
            )

            # how many files to process, comment out to process all files
            count += 1
            if count >= process_files_per_run:
                break

    print("ProcessJSONtoDB complete!")

    return count


# end ProcessJSONtoDB


def moveProcessedKeys(**kwargs):
    logging.info("movePorcessedKeys called")
    keys = kwargs["ti"].xcom_pull(key="processedKeys")

    hook = S3Hook(aws_conn_id="s3_conn")
    logging.info("Got S3 Hook")
    bucket_source_name = Variable.get("waze_s3_bucket_source")
    bucket_processed_name = Variable.get("waze_s3_bucket_processed")
    # bucket_source = s3.Bucket(bucket_source_name)
    bucket_processed = hook.get_bucket(bucket_processed_name)

    logging.info("keys:")
    for key in keys:
        logging.info(key)
        # copy file to processed S3 bucket and delete from 'test' bucket
        copy_source = {"Bucket": bucket_source_name, "Key": key}
        logging.info(copy_source)
        bucket_processed.copy(copy_source, key)
        logging.info(
            "copied "
            + key
            + " from "
            + bucket_source_name
            + " to "
            + bucket_processed_name
        )

        # delete file
        keyObj = hook.get_key(key, bucket_name=bucket_source_name)
        logging.info("Deleted " + key + " from " + bucket_source_name)
        keyObj.delete()

    logging.info("moveProcessedKeys complete!")


processDataFileOp = PythonOperator(
    task_id="processDataFile",
    python_callable=processJSONtoDB,
    provide_context=True,
    dag=dag,
)

# order of execution of tasks
dag >> processDataFileOp
