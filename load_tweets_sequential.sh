#!/bin/bash

files=$(find data/*)

echo '================================================================================'
echo 'load denormalized'
echo '================================================================================'
for file in $files; do 
    time unzip -p "$file" | sed 's/\\u0000//g' | psql postgresql://postgres:pass@localhost:1219/ -c "COPY tweets_jsonb (data) FROM STDIN csv quote e'\x01' delimiter e'\x02';"
done

echo '================================================================================'
echo 'load pg_normalized'
echo '================================================================================'
#for file in $file; do
#time python3 -u load_tweets.py --db=postgresql://postgres:pass@localhost:2219/ --inputs $files
#done

echo '================================================================================'
echo 'load pg_normalized_batch'
echo '================================================================================'
#time for file in $file; do
time python3 -u load_tweets_batch.py --db=postgresql://postgres:pass@localhost:32199/ --inputs $files
#done
