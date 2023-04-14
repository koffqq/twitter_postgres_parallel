#!/usr/bin/python3

# process command line args
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--db',required=True)
parser.add_argument('--inputs',nargs='+',required=True)
parser.add_argument('--print_every',type=int,default=1000)
args = parser.parse_args()

# imports
import sqlalchemy
import os
import datetime
import zipfile
import io
import json

# create database connection
engine = sqlalchemy.create_engine(args.db, connect_args={
    'application_name': 'load_tweets.py',
    })
connection = engine.connect()

################################################################################
# helper functions
################################################################################

def remove_nulls(s):
    r'''
    Postgres doesn't support strings with the null character \x00 in them, but twitter does.
    This helper function replaces the null characters with an escaped version so that they can be loaded into postgres.
    Technically, this means the data in postgres won't be an exact match of the data in twitter,
    and there is no way to get the original twitter data back from the data in postgres.

    The null character is extremely rarely used in real world text (approx. 1 in 1 billion tweets),
    and so this isn't too big of a deal.
    A more correct implementation, however, would be to *escape* the null characters rather than remove them.
    This isn't hard to do in python, but it is a bit of a pain to do with the JSON/COPY commands for the denormalized data.
    Since our goal is for the normalized/denormalized versions of the data to match exactly,
    we're not going to escape the strings for the normalized data.

    >>> remove_nulls('\x00')
    ''
    >>> remove_nulls('hello\x00 world')
    'hello world'
    '''
    if s is None:
        return None
    else:
        return s.replace('\x00','\\x00')


def get_id_urls(url):
    '''
    Given a url, returns the corresponding id in the urls table.
    If no row exists for the url, then one is inserted automatically.
    '''
    sql = sqlalchemy.sql.text('''
    insert into urls 
        (url)
        values
        (:url)
    on conflict do nothing
    returning id_urls
    ;
    ''')
    res = connection.execute(sql,{'url':url}).first()
    if res is None:
        sql = sqlalchemy.sql.text('''
        select id_urls 
        from urls
        where
            url=:url
        ''')
        res = connection.execute(sql,{'url':url}).first()
    id_urls = res[0]
    return id_urls


################################################################################
# main functions
################################################################################

def insert_tweet(connection,tweet):
    '''
    Inserts the tweet into the database.

    Args:
        connection: a sqlalchemy connection to the postgresql db
        tweet: a dictionary representing the json tweet object
    '''
    # skip tweet if it's already inserted
    with connection.begin() as trans:
        sql=sqlalchemy.sql.text('''
        SELECT id_tweets 
        FROM tweets
        WHERE id_tweets = :id_tweets
    ''')
        res = connection.execute(sql,{
        'id_tweets':tweet['id'],
        })
        if res.first() is not None:
            return

    # insert tweet within a transaction;
    # this ensures that a tweet does not get "partially" loaded
    #connection.commit()
    #with connection.begin() as trans:

        ########################################
        # insert into the users table
        ########################################
        if tweet['user']['url'] is None:
            user_id_urls = None
        else:
            user_id_urls = get_id_urls(tweet['user']['url'])

        # create/update the user
        sql = sqlalchemy.sql.text('''
        INSERT INTO users
            (id_users,created_at,updated_at,screen_name,name,location,id_urls,description,protected,verified,friends_count,listed_count,favourites_count,statuses_count,withheld_in_countries)
            VALUES
            (:id_users,:created_at,:updated_at,:screen_name,:name,:location,:id_urls,:description,:protected,:verified,:friends_count,:listed_count,:favourites_count,:statuses_count,:withheld_in_countries)
            ON CONFLICT (id_users) DO
            NOTHING
            ''')
            # NOTE:
            # doing the following on conflict is slightly more correct as it would allow us
            # to overwrite older versions of a user's information with newer versions;
            # but it is significantly slower because it introduces a lock on the table
            # that causes other insertion processes to wait.
            #UPDATE SET
                #created_at=:created_at,
                #updated_at=:updated_at,
                #screen_name=:screen_name,
                #name=:name,
                #location=:location,
                #id_urls=:id_urls,
                #description=:description,
                #protected=:protected,
                #verified=:verified,
                #friends_count=:friends_count,
                #listed_count=:listed_count,
                #favourites_count=:favourites_count,
                #statuses_count=:statuses_count,
                #withheld_in_countries=:withheld_in_countries
                #WHERE :updated_at > users.updated_at OR users.updated_at is null
        res = connection.execute(sql,{
            'id_users':tweet['user']['id'],
            'created_at':tweet['user']['created_at'],
            'updated_at':tweet['created_at'],
            'screen_name':remove_nulls(tweet['user']['screen_name']),
            'name':remove_nulls(tweet['user']['name']),
            'location':remove_nulls(tweet['user']['location']),
            'id_urls':user_id_urls,
            'description':remove_nulls(tweet['user']['description']),
            'protected':tweet['user']['protected'],
            'verified':tweet['user']['verified'],
            'friends_count':tweet['user']['friends_count'],
            'listed_count':tweet['user']['listed_count'],
            'favourites_count':tweet['user']['favourites_count'],
            'statuses_count':tweet['user']['statuses_count'],
            'withheld_in_countries':tweet['user'].get('withheld_in_countries',None),
            })

        ########################################
        # insert into the tweets table
        ########################################

        try:
            geo_coords = tweet['geo']['coordinates']
            geo_coords = str(tweet['geo']['coordinates'][0]) + ' ' + str(tweet['geo']['coordinates'][1])
            geo_str = 'POINT'
        except TypeError:
            try:
                geo_coords = '('
                for i,poly in enumerate(tweet['place']['bounding_box']['coordinates']):
                    if i>0:
                        geo_coords+=','
                    geo_coords+='('
                    for j,point in enumerate(poly):
                        geo_coords+= str(point[0]) + ' ' + str(point[1]) + ','
                    geo_coords+= str(poly[0][0]) + ' ' + str(poly[0][1])
                    geo_coords+=')'
                geo_coords+=')'
                geo_str = 'MULTIPOLYGON'
            except KeyError:
                if tweet['user']['geo_enabled']:
                    geo_str = None
                    geo_coords = None

        try:
            text = tweet['extended_tweet']['full_text']
        except:
            text = tweet['text']

        try:
            country_code = tweet['place']['country_code'].lower()
        except TypeError:
            country_code = None

        if country_code == 'us':
            state_code = tweet['place']['full_name'].split(',')[-1].strip().lower()
            if len(state_code)>2:
                state_code = None
        else:
            state_code = None

        try:
            place_name = tweet['place']['full_name']
        except TypeError:
            place_name = None

        # NOTE:
        # The tweets table has the following foreign key:
        # > FOREIGN KEY (in_reply_to_user_id) REFERENCES users(id_users)
        #
        # This means that every "in_reply_to_user_id" field must reference a valid entry in the users table.
        # If the id is not in the users table, then you'll need to add it in an "unhydrated" form.
        if tweet.get('in_reply_to_user_id',None) is not None:
            sql=sqlalchemy.sql.text('''
            INSERT INTO users
                (id_users,screen_name)
                VALUES
                (:id_users,:screen_name)
            ON CONFLICT DO NOTHING
                ''')
            res = connection.execute(sql,{
                'id_users':tweet['in_reply_to_user_id'],
                'screen_name':tweet['in_reply_to_screen_name'],
                })

        # insert the tweet
        sql=sqlalchemy.sql.text(f'''
        INSERT INTO tweets
            (id_tweets,id_users,created_at,in_reply_to_status_id,in_reply_to_user_id,quoted_status_id,geo,retweet_count,quote_count,favorite_count,withheld_copyright,withheld_in_countries,place_name,country_code,state_code,lang,text,source)
            VALUES
            (:id_tweets,:id_users,:created_at,:in_reply_to_status_id,:in_reply_to_user_id,:quoted_status_id,ST_GeomFromText(:geo_str || '(' || :geo_coords || ')'),:retweet_count,:quote_count,:favorite_count,:withheld_copyright,:withheld_in_countries,:place_name,:country_code,:state_code,:lang,:text,:source)
        ON CONFLICT DO NOTHING;
            ''')
        res = connection.execute(sql,{
            'id_tweets':tweet['id'],
            'id_users':tweet['user']['id'],
            'created_at':tweet['created_at'],
            'in_reply_to_status_id':tweet.get('in_reply_to_status_id',None),
            'in_reply_to_user_id':tweet.get('in_reply_to_user_id',None),
            'quoted_status_id':tweet.get('quoted_status_id',None),
            'geo_coords':geo_coords,
            'geo_str':geo_str,
            'retweet_count':tweet.get('retweet_count',None),
            'quote_count':tweet.get('quote_count',None),
            'favorite_count':tweet.get('favorite_count',None),
            'withheld_copyright':tweet.get('withheld_copyright',None),
            'withheld_in_countries':tweet.get('withheld_in_countries',None),
            'place_name':place_name,
            'country_code':country_code,
            'state_code':state_code,
            'lang':tweet.get('lang'),
            'text':remove_nulls(text),
            'source':remove_nulls(tweet.get('source',None)),
            })

        ########################################
        # insert into the tweet_urls table
        ########################################

        try:
            urls = tweet['extended_tweet']['entities']['urls']
        except KeyError:
            urls = tweet['entities']['urls']

        for url in urls:
            id_urls = get_id_urls(url['expanded_url'])

            sql=sqlalchemy.sql.text('''
            INSERT INTO tweet_urls
                (id_tweets,id_urls)
                VALUES
                (:id_tweets,:id_urls)
            ON CONFLICT DO NOTHING
                ''')
            res = connection.execute(sql,{
                'id_tweets':tweet['id'],
                'id_urls':id_urls,
                })

        ########################################
        # insert into the tweet_mentions table
        ########################################

        try:
            mentions = tweet['extended_tweet']['entities']['user_mentions']
        except KeyError:
            mentions = tweet['entities']['user_mentions']

        for mention in mentions:
            sql=sqlalchemy.sql.text('''
            INSERT INTO users
                (id_users,name,screen_name)
                VALUES
                (:id_users,:name,:screen_name)
            ON CONFLICT DO NOTHING
                ''')
            res = connection.execute(sql,{
                'id_users':mention['id'],
                'name':remove_nulls(mention['name']),
                'screen_name':remove_nulls(mention['screen_name']),
                })

            sql=sqlalchemy.sql.text('''
            INSERT INTO tweet_mentions
                (id_tweets,id_users)
                VALUES
                (:id_tweets,:id_users)
            ON CONFLICT DO NOTHING
                ''')
            res = connection.execute(sql,{
                'id_tweets':tweet['id'],
                'id_users':mention['id']
                })

        ########################################
        # insert into the tweet_tags table
        ########################################

        try:
            hashtags = tweet['extended_tweet']['entities']['hashtags'] 
            cashtags = tweet['extended_tweet']['entities']['symbols'] 
        except KeyError:
            hashtags = tweet['entities']['hashtags']
            cashtags = tweet['entities']['symbols']

        tags = [ '#'+hashtag['text'] for hashtag in hashtags ] + [ '$'+cashtag['text'] for cashtag in cashtags ]

        for tag in tags:
            sql=sqlalchemy.sql.text('''
            INSERT INTO tweet_tags
                (id_tweets,tag)
                VALUES
                (:id_tweets,:tag)
            ON CONFLICT DO NOTHING
                ''')
            res = connection.execute(sql,{
                'id_tweets':tweet['id'],
                'tag':remove_nulls(tag)
                })

        ########################################
        # insert into the tweet_media table
        ########################################

        try:
            media = tweet['extended_tweet']['extended_entities']['media']
        except KeyError:
            try:
                media = tweet['extended_entities']['media']
            except KeyError:
                media = []

        for medium in media:
            id_urls = get_id_urls(medium['media_url'])
            sql=sqlalchemy.sql.text('''
            INSERT INTO tweet_media
                (id_tweets,id_urls,type)
                VALUES
                (:id_tweets,:id_urls,:type)
            ON CONFLICT DO NOTHING
                ''')
            res = connection.execute(sql,{
                'id_tweets':tweet['id'],
                'id_urls':id_urls,
                'type':medium['type']
                })


# loop through file
# NOTE:
# we reverse sort the filenames because this results in fewer updates to the users table,
# which prevents excessive dead tuples and autovacuums
for filename in sorted(args.inputs, reverse=True):
    with zipfile.ZipFile(filename, 'r') as archive: 
        #with connection.begin() as trans:
            print(datetime.datetime.now(),filename)
            for subfilename in sorted(archive.namelist(), reverse=True):
                with io.TextIOWrapper(archive.open(subfilename)) as f:
                    for i,line in enumerate(f):
                        tweet = json.loads(line)
                        insert_tweet(connection,tweet)

                        # print message
                        if i%args.print_every==0:
                            print(datetime.datetime.now(),filename,subfilename,'i=',i,'id=',tweet['id'])
