# Parallel Twitter in Postgres

![](https://github.com/koffqq/twitter_postgres_parallel/workflows/tests_normalized/badge.svg)

![](https://github.com/koffqq/twitter_postgres_parallel/workflows/tests_normalized_parallel/badge.svg)

![](https://github.com/koffqq/twitter_postgres_parallel/workflows/tests_normalized_batch/badge.svg)

![](https://github.com/koffqq/twitter_postgres_parallel/workflows/tests_normalized_batch_parallel/badge.svg)

![](https://github.com/koffqq/twitter_postgres_parallel/workflows/tests_denormalized/badge.svg)

![](https://github.com/koffqq/twitter_postgres_parallel/workflows/tests_denormalized_parallel/badge.svg)

In this assignment, you will make your data loading into postgres significantly faster using batch loading and parallel loading.
Notice that many of the test cases above are already passing;
you will have to ensure that they remain passing as you complete the tasks below.

## Tasks

### Setup

1. Fork this repo
1. Enable github action on your fork
1. Clone the fork onto the lambda server
1. Modify the `README.md` file so that all the test case images point to your repo
1. Modify the `docker-compose.yml` to specify valid ports for each of the postgres services
    1. recall that ports must be >1024 and not in use by any other user on the system
    1. verify that you have modified the file correctly by running
       ```
       $ docker-compose up
       ```
       with no errors

### Sequential Data Loading

Bring up a fresh version of your containers by running the commands:
```
$ docker-compose down
$ docker volume prune
$ docker-compose up -d --build
```

Run the following command to insert data into each of the containers sequentially.
(Note that you will have to modify the ports to match the ports of your `docker-compose.yml` file.)
```
$ sh load_tweets_sequential.sh
```
Record the elapsed time in the table in the Submission section below.
You should notice that batching significantly improves insertion performance speed.

> **NOTE:**
> The `time` command outputs 3 times:
>
> 1. The `elapsed` time (also called wall-clock time) is the actual amount of time that passes on the system clock between the program's start and end.
>    This is what should be recorded in the table above.
>
> 1. The `user` time is the total amount of CPU time used by the program.
>    This can be different than wall-clock time for 2 reasons:
>
>    1. If the process uses multiple CPUs, then all of the concurrent CPU time is added together.
>       For example, if a process uses 8 CPUS, then the `user` time could be up to 8 times higher than the actual wall-clock time.
>       (Your sequential process in this section is single threaded, so this won't be applicable; but this will be applicable for the parallel process in the next section.)
>
>    1. If the command has to wait on an external resource (e.g. disk/network IO),
>       then this waiting time is not included.
>       (Your python processes will have to wait on the postgres server,
>       and the postgres server's processing time is not included in the `user` time because it is a different process.
>       In general, the postgres server could be running on an entirely different machine.)
>
> 1. The `system` time is the total amount of CPU time used by the Linux kernel when managing this process.
>    For the vast majority of applications, this will be a very small amount.

### Parallel Data Loading

There are 10 files in `/data` folder of this repo.
If we process each file in parallel, then we should get a theoretical 10x speed up.
The file `load_tweets_parallel.sh` will insert the data in parallel and get nearly a 10-fold speedup,
but there are several changes that you'll have to make first to get this to work.

#### Denormalized Data

Currently, there is no code in the `load_tweets_parallel.sh` file for loading the denormalized data.
Your first task is to use the GNU `parallel` program to load this data.

Complete the following steps:

1. Write a POSIX script `load_denormalized.sh` that takes a single parameter as input that represents a data file.
   The script should then load this file into the database using the same technique as in the `load_tweets_sequential.sh` file for the denormalized database.
   In particular, you know you've implemented this file correctly if the following bash code correctly loads the database.
   ```
   for file in $(find data); do
       sh load_denormalized.sh $file
   done
   ```

2. Call the `load_denormalized.sh` file using the `parallel` program from within the `load_tweets_parallel.sh` script.
   You know you've completed this step correctly if the `check-answers.sh` script passes and the test badge turns green.

#### Normalized Data (unbatched)

Parallel loading of the unbatched data should "just work."
The code in the `load_tweets.py` file is structured so that you never run into deadlocks.
Unfortunately, the code is extremely slow,
so even when run in parallel it is still slower than the batched code.

> **NOTE:**
> The `tests_normalized_batch_parallel` is currently failing because the `load_tweets_parallel.sh` script is not yet implemented.
> After you use GNU parallel to implement this script, everything should pass.

#### Normalized Data (batched)

Parallel loading of the batched data will fail due to deadlocks.
These deadlocks will cause some of your parallel loading processes to crash.
So all the data will not get inserted,
and you will fail the `check-answers.sh` tests.

There are two possible ways to fix this.
The most naive method is to catch the exceptions generated by the deadlocks in python and repeat the failed queries.
This will cause all of the data to be correctly inserted,
so you will pass the test cases.
Unfortunately, python will have to repeat queries so many times that the parallel code will be significantly slower than the sequential code.
My code took several hours to complete!

So the best way to fix this problem is to prevent the deadlocks in the first place.

<img src=you-cant-have-a-deadlock-if-you-remove-the-locks.jpg width=600px />

In this case, the deadlocks are caused by the `UNIQUE` constraints,
and so we need to figure out how to remove those constraints.
This is unfortunately rather complicated.

The most difficult `UNIQUE` constraint to remove is the `UNIQUE` constraint on the `url` field of the `urls` table.
The `get_id_urls` function relies on this constraint, and there is no way to implement this function without the `UNIQUE` constraint.
So to delete this constraint, we will have to denormalize the representation of urls in our database.
Perform the following steps to do so:

1. Modify the `services/pg_normalized_batch/schema.sql` file by:
   1. deleting the `urls` table
   1. replacing all of the `id_urls BIGINT` columns with a `url TEXT` column
   1. deleting all foreign keys that connected the old `id_urls` columns to the `urls` table

1. Modify the `load_tweets_batch.py` file by:
   1. deleting the `get_id_urls` function
   1. modifying all of the references to the id generated by `get_id_urls` to directly store the url in the `url` field of the table

There are also several other `UNIQUE` constraints (mostly in `PRIMARY KEY`s) that need to be removed from other columns of the table.
Once you remove these constraints, this will cause downstream errors in both the SQL and Python that you will have to fix.
(But I'm not going to tell you what these errors look like in advance... you'll have to encounter them on your own.)

> **NOTE:**
> In a production database where you are responsible for the consistency of your data,
> you would never want to remove these constraints.
> In our case, however, we're not responsible for the consistency of the data.
> We want to represent the data exactly how Twitter represents it "upstream",
> and so Twitter are responsible for ensuring the consistency.

#### Results

Once you have verified the correctness of your parallel code,
bring up a fresh instances of your containers and measure your code's runtime with the command
```
$ sh load_tweets_parallel.sh
```
Record the elapsed times in the table below.
You should notice that parallelism achieves a nearly (but not quite) 10x speedup in each case.

## Submission

Ensure that your runtimes on the lambda server are recorded below.

|                        | elapsed time (sequential) | elapsed time (parallel) |
| -----------------------| ------------------------- | ------------------------- |
| `pg_normalized`        |                           |                           | 
| `pg_normalized_batch`  |                           |                           | 
| `pg_denormalized`      |                           |                           | 

Then upload a link to your forked github repo on sakai.

> **GRADING NOTE:**
> It is not enough to just get passing test cases for this assignment in order to get full credit.
> (It is easy to pass the test cases by just doing everything sequentially.)
> Instead, you must also implement the parallelism correctly so that the parallel runtimes above are about 10x faster than the sequential runtimes.
