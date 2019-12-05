# Aqueduct
A shared pipeline for building ETLs and batch jobs that we run at the City of LA for Data Science Projects. Built on Apache Airflow.

Lots of the following code and documentation was based on the excellent [Mozilla-Telemetry](https://raw.githubusercontent.com/mozilla/telemetry-airflow/master/README.md) project.

## Contributors
* Robert Pangalian
* Hunter Owens
* Bryan Blackford
* Eirik Lin

### Prerequisites

This app is built and deployed locally with
[docker](https://docs.docker.com/) and
[docker-compose](https://docs.docker.com/compose/).

### Build Container

An Airflow container can be built with

```bash
make build
```

You should then run the database migrations to complete the container initialization with

```bash
make migrate
```

There are some unresolved issues with WSL, Docker for Windows and such. Waiting for WSL 2. To fix, run

```
sudo mkdir /c
sudo mount --bind /mnt/c /c
```

and read this [blog post](https://nickjanetakis.com/blog/setting-up-docker-for-windows-and-wsl-to-work-flawlessly) for context.
## Testing

A single task, e.g. `spark`, of an Airflow dag, e.g. `example`, can be run with an execution date, e.g. `2018-01-01`, in the `dev` environment with:
```bash
export AWS_SECRET_ACCESS_KEY=...
export AWS_ACCESS_KEY_ID=...
make run COMMAND="test example spark 20180101"
```

The container will run the desired task to completion (or failure).
Note that if the container is stopped during the execution of a task,
the task will be aborted. In the example's case, the Spark job will be
terminated.

The logs of the task can be inspected in real-time with:
```bash
docker logs -f telemetryairflow_scheduler_1
```

You can task logs and see cluster status on
[the EMR console](https://us-west-2.console.aws.amazon.com/elasticmapreduce/home?region=us-west-2)

By default, the results will end up in the `telemetry-test-bucket` in S3.
If your desired task depends on other views, it will expect to be able to find those results
in `telemetry-test-bucket` too. It's your responsibility to run the tasks in correct
order of their dependencies.

### Local Deployment

Assuming you're using macOS and Docker for macOS, start the docker service,
click the docker icon in the menu bar, click on preferences and change the
available memory to 4GB.

To deploy the Airflow container on the docker engine, with its required dependencies, run:
```bash
make up
```

You can now connect to your local Airflow web console at
`http://localhost:8000/`.

All DAGs are paused by default for local instances and our staging instance of Airflow.
In order to submit a DAG via the UI, you'll need to toggle the DAG from "Off" to "On",
but be very careful to check what DAG runs are generated (Browse > DAG Runs), since it may start
generating backfill runs based on the DAG's configured start date, which could get very expensive
(set `schedule_interval=None` in your DAG definition to prevent these scheduled runs).
You'll likely want to toggle the DAG back to "Off" as soon as your desired task starts running.


#### Workaround for permission issues

Users on Linux distributions will encounter permission issues with `docker-compose`.
This is because the local application folder is mounted as a volume into the running container.
The Airflow user and group in the container is set to `10001`.

To work around this, replace all instances of `10001` in `Dockerfile.dev` with the host user id.

```bash
sed -i "s/10001/$(id -u)/g" Dockerfile.dev

```

### Production Setup

![Aqueductagram](Aqueduct.png)


To deploy to production, [AWS Codedeploy](https://aws.amazon.com/codedeploy/) automatically pushes master to all the worker nodes / resets the system.

Open a PR againist master and it will be deployed.

Currently, we do not autodeploy to the master node and you have to run the steps by hand. Working with Cloud team to fix.

### Debugging

Some useful docker tricks for development and debugging:

```bash
# Stop all docker containers:
docker stop $(docker ps -aq)

# Remove any leftover docker volumes:
docker volume rm $(docker volume ls -qf dangling=true)
```

### Triggering a task to re-run within the Airflow UI

- Check if the task / run you want to re-run is visible in the DAG's Tree View UI
  - For example, [the `main_summary` DAG tree view](http://workflow.telemetry.mozilla.org/admin/airflow/tree?num_runs=25&root=&dag_id=main_summary).
  - Hover over the little squares to find the scheduled dag run you're looking for.
- If the dag run is not showing in the Dag Tree View UI (maybe deleted)
  - Browse -> Dag Runs
  - Create (you can look at another dag run of the same dag for example values too)
    - Dag Id: the name of the dag, for example, `main_summary` or `crash_aggregates`
    - Execution Date: The date the dag should have run, for example, `2018-05-14 00:00:00`
    - Start Date: Some date between the execution date and "now", for example, `2018-05-20 00:00:05`
    - End Date: Leave it blank
    - State: success
    - Run Id: `scheduled__2018-05-14T00:00:00`
    - External Trigger: unchecked
  - Click Save
  - Click on the Graph view for the dag in question. From the main DAGs view, click the name of the DAG
  - Select the "Run Id" you just entered from the drop-down list
  - Click "Go"
  - Click each element of the DAG and "Mark Success"
  - The tasks should now show in the Tree View UI
- If the dag run is showing in the DAG's Tree View UI
  - Click on the small square for the task you want to re-run
  - **Uncheck** the "Downstream" toggle
  - Click the "Clear" button
  - Confirm that you want to clear it
  - The task should be scheduled to run again straight away.

### Triggering backfill tasks using the CLI

- SSH into the `aqueduct-airflow` instance.
- Run the desired backfill command, something like `$ airflow backfill main_summary -s 2018-05-20 -e 2018-05-26`

## Install Issues

1. Installing on a network with a proxy (such as LA City) may require setting proxy settings for these applications. Your proxy server address can be found in your system settings or by asking your network admin.

1a. Anaconda: (Reference: https://conda.io/docs/user-guide/configuration/use-winxp-with-proxy.html )
Edit the file .condarc (in Windows: \users\{username}\ )
and add these 3 lines (with proxy and port address filled in):
proxy_servers:
    http: http://proxy:port
    https: https://proxy:port

1b. Set pip and python proxies by setting the http_proxy and https_proxy system variables to your proxy server.

1c. Anaconda may call pip to install some modules, but it may not work with the pip proxies you setup. One way around this is to run pip install with proxy options from the command line. After conda failed to pip install flask, run this command line: `pip install --proxy=http://proxy:port flask` and then run the conda line again.
