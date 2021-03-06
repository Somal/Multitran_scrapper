# -*- coding: utf-8 -*-
"""
This script parses all dictionaries from Multitran.
See dictionaries on http://www.multitran.com/m.exe?CL=1&s&l1=1&l2=2&SHL=2
Firstly, the parser goes to main page (above) and goes to every dictionary.
    On dictionary page, it parses all available rows (words) and go to next page ('>>' on the page)
        until count of handled translations less than count words in dictionary (parsed from main page)
After parsing of translation, it stores into Item and use Pipeline for storing into DB.
Pipeline uses SqlAlchemy for DB connections.
DB has UNIQUE_CONSTRAINT on pair (word, dictionary) for duplicate disappearing.

So process_item from pipeline try to store translation into DB.
And if attempt is failed than we shouldn't increase count of handled translations (stored in response's meta).
So it's the main reason of storing Item and Pipeline into the spider's file.

DONE:
 - The core of parser which goes on all dictionaries and on translations using button '>>' on every link
 - Update dictionary handling exitpoint: parses all rows until count of stored (handled) translations less than dictionary's size
    instead of continuously moving pressing '>>'
 - Add TimeOut exception handler which is connected with long downloading
 - Add support store in DB
 - Update DB: add UNIQUE_CONSTRAINT for distinct rows storing
 - Dump on 1 million values
TO DO:
 - Run, run, run!

It hasn't input files, because the parser should download full Multitran without filtering.
An output file - long csv file with all translations. The structure:
    'dictionary', 'word', 'translation', 'author_name', 'author_link'


"""
import csv  # Standard library for table processing (I/O)

import scrapy
from scrapy import Request
from sqlalchemy import *
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from twisted.internet.error import TimeoutError  # It's used for TimeOut handling

from multitran_scrapper.items import TranslationItem  # The item for storing into DB
from .database import \
    DATABASE  # Local Python's file which includes only dictionary DATABASE with connection data in SQLAlchemy format

# Standard SQLAlchemy part
DeclarativeBase = declarative_base()


def db_connect():
    """
    Performs database connection using database settings from settings.py.
    Returns sqlalchemy engine instance
    """
    return create_engine(URL(**DATABASE))


def create_translation_table(engine):
    DeclarativeBase.metadata.create_all(engine)


# Description of table with constraint
class Translation(DeclarativeBase):
    __tablename__ = "dictionaries_unique"

    id = Column(Integer, primary_key=True)
    dictionary = Column('dictionary', String)
    word = Column('word', String)
    translation = Column('translation', String)
    author_name = Column('author_name', String, nullable=True)
    author_link = Column('author_link', String, nullable=True)
    __table_args__ = (UniqueConstraint('dictionary', 'word', name='unique_constraint'),)  # Not tested


class MultitranScrapperPipeline(object):
    def __init__(self):
        engine = db_connect()
        create_translation_table(engine)
        self.Session = sessionmaker(bind=engine)

    def process_item(self, item):
        session = self.Session()
        translation = Translation(**item)
        result = True

        try:
            session.add(translation)
            session.commit()
        except:
            session.rollback()
            result = False
        finally:
            session.close()

        return result


# Pipeline's initialization. Many pipeline shouldn't be.
pipeline = MultitranScrapperPipeline()

# Settings
# Delimiter and quotechar are parameters of csv file. You should know it if you created the file
CSV_DELIMITER = '	'
CSV_QUOTECHAR = '"'  # '|'
USE_DATABASE = True  # Flag for DB use. For it you should create database.py with SqlAlchemy's config (python's list)


class MultitranSpider(scrapy.Spider):
    name = "multitran_all_dictionaries"  # Name for crawling
    host = 'http://www.multitran.com'  # Spider's service info. It will be used in script below.

    def __init__(self):
        self.timeout_errors = open('timeout.txt', 'w')  # The file for url storing when timeout error
        # Storing into CSV file
        if not USE_DATABASE:
            self.output_file = open('dictionaries.csv', 'w')
            self.output_writer = csv.writer(self.output_file, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTECHAR,
                                            quoting=csv.QUOTE_ALL)

    def start_requests(self):
        """
        This method is a start point for parsing.
        :return: list with one start Request which specifies on main page
        """
        return [Request("http://www.multitran.com/m.exe?CL=1&s&l1=1&l2=2&SHL=2", callback=self.parser)]

    def parser(self, response):
        """
        The method which finds links of all dictionaries
        :param response: Scrapy's response
        :return: requests for every dictionaries
        """
        DICTIONARY_XPATH = '//*/tr/td[1]/a'
        TRANSLATION_COUNT_XPATH = 'ancestor::tr/td[2]/text()'
        for dictionary in response.xpath(DICTIONARY_XPATH)[1:-1]:  # Cut out first and last service rows
            name = dictionary.xpath('text()').extract_first()
            link = dictionary.xpath('@href').extract_first()
            count = int(dictionary.xpath(TRANSLATION_COUNT_XPATH).extract_first())  # Size of dictionary
            yield Request(url=self.host + link, callback=self.dictionary_parser,
                          meta={'name': name, 'handled_translations': 0, 'max_count': count})

    def dictionary_parser(self, response):
        """
        The method which parses all translations in the specific dictionary
        :param response:
        :return:
        """
        END_FLAG = False
        ROW_XPATH = '//*/tr'
        name = response.meta['name']
        for row in response.xpath(ROW_XPATH):
            row_value = [None] * 5
            row_value[0] = name
            row_value[1] = "".join(
                row.xpath('td[@class="termsforsubject"][1]/descendant-or-self::node()/text()').extract())  # Word
            row_value[2] = "".join(
                row.xpath('td[@class="termsforsubject"][2]/descendant-or-self::node()/text()').extract())  # Translation
            row_value[3] = row.xpath('td[@class="termsforsubject"][3]/a/i/text()').extract()  # Author's name
            row_value[4] = row.xpath('td[@class="termsforsubject"][3]/a/@href').extract()  # Author's link
            # Check type of data: useful (translations) or useless (service)
            if len(row_value[3]) > 0:
                row_value[3] = row_value[3][0]
                row_value[4] = row_value[4][0]
            else:
                row_value[3] = ''
                row_value[4] = ''
            if len(row_value[1]) > 0:
                if USE_DATABASE:
                    # About zip: https://docs.python.org/3/library/functions.html#zip
                    values_dict = dict(
                        zip(['dictionary', 'word', 'translation', 'author_name', 'author_link'], row_value))
                    item = TranslationItem(values_dict)  # Wrapper of data
                    db_status = pipeline.process_item(item)  # Try to store resulting translations into DB
                    if db_status:
                        # If saving is OK
                        response.meta['handled_translations'] += 1
                        # else:
                        #     self.logger.info('Exception')
                else:
                    self.output_writer.writerow(row_value)  # Save data to csv file
                    response.meta[
                        'handled_translations'] += 1  # We can't check UNIQUE_CONSTRAINT in csv and so always increase value

            # Exitpoint of dictionary's parsing
            # Check count of handled translation
            if response.meta['handled_translations'] >= response.meta['max_count']:
                END_FLAG = True
                break

        next_link = response.xpath('//*/a[contains(text(),">>")]/@href').extract()
        if len(next_link) > 0 and not END_FLAG:
            yield Request(url=self.host + next_link[0], callback=self.dictionary_parser, meta=response.meta)

    # The method which handled TimeOut exception
    def errback_httpbin(self, failure):
        if failure.check(TimeoutError):
            self.timeout_errors.write("{}\n".format(failure.value.response.value))

    def close(self, reason):
        self.timeout_errors.close()
        if not USE_DATABASE:
            self.output_file.close()
