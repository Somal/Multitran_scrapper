# -*- coding: utf-8 -*-
"""
It's the main parser of Multitran translation system.

DONE:
 - Input/Output
 - Core of auto-translation: parsing of multitran by specific word
 - Recommendation system v 1.2

TO DO:
 - Update recommendation system using different blocks
 - Maybe rewrite code for use Pandas as table engine instead of csv (optional)


It has input csv file which contains words for translation as one column.

*** Please, see Description.docx. It contains detailed description,
    but it includes information of one-to-many translations (one word has several translations).
    The last version of parser select only recommended translation and save only it to DB
***

For every word from input file, the parser creates several columns of information and saves to output csv file:
  input_word | translation | dictionary of translation (из какого словаря взят перевод) | block_number | author_name | link on author | author's comment
Another form:  ['Input word', 'Translations', 'Dictionary', 'Block number', 'Block name', 'Author', 'Link on author',
           'Comment']
Some comments of data:
 - any word has several translations from different blocks
 - if you want to have only recommended translations, you should set ONLY_RECOMMENDATED_TRANSLATIONS = True, otherwise False
 - please, read Description.docx for find block's definition
 - also input file can has several columns and you can set a column as input word using TRANSLATE_WORD_INDEX. Others columns will be copied automatically
 - Link of author is a relative path, i.e. /m.exe?a=32424&UserName=Ivan.
    So you should concatenate it with 'www.multitran' with some settings of multitran (see above).
 - Start URL is http://www.multitran.com/m.exe?CL=1&s={}&l1=1&l2=2&SHL=2 where {} is a requested word.
    l1=1 means from English, l2=2 means to Russian, SHL=2 means Russian interface of site (name of dictionaries etc.), CL - ???

## Parsing speed increasing (important settings):
For it, you should change settings.py.
The Scrapy is based on asynchronous framework Twisted. Please see good lecture about async http://cs.brown.edu/courses/cs168/s12/handouts/async.pdf
So Twisted has several flows. Flows are conditionally "concurrent".
And so settings.py includes CONCURRENT_REQUESTS. It's count of flows. And you should set it.
Of course, bigger CONCURRENT_REQUESTS provides big speed, but it can creates some errors, for example TimeError.
With big speed the parser tries to download many links simultaneously and someone can stuck.
When time is not critical, you should set CONCURRENT_REQUESTS < 16 otherwise > 16.
For timeout error solving, you can increase DOWNLOAD_TIMEOUT (in sec).

Also you can except some dictionaries for some narrow parsing using EXCEPTED_DICTIONARIES (dictionary abbreviation list).
This script has two sides: engineering and analysis. All tasks connected with parsing are engineering. Recommendation system for translations is the analysis.

# Recommendation translations
See the current version in MultitranSpider.write_translations.recommend_translation

DONE:
    1.Если на странице есть несколько блоков по одному и тому же словарю, то для этого набора блоков должен выбираться один рекомендуемый перевод
        Имеются в виду такие случаи (новый интерфейс мультитрана):

 возможность IP n
    progr. IP capability (ssn)
 возможность VPN n
    progr. VPN capability (ssn)

То есть у нас должен быть только один рекомендованный перевод не просто на один блок, но и на один словарь. Не может быть два рекомендованных перевода из одного и того же словаря.

2.Нам надо отказываться от фраз, которые длиннее или короче, чем искомая фраза, при сборе переводов. Нам нужны только точные совпадения.
Например, мы искали слово "возможность"
Блоки " возможность n" и "возможности n" подходят (n видимо означает noun - часть речи "существительное")
Но идущие дальше блоки " (представившаяся) возможность n",  "возможность IP n", "возможность VPN n", т.к. в этих блоках фраза длиннее, чем поисковое условие. Мы искали "возможность," но мы не искали слово IP рядом со словом возможность. Точно так же, если бы мы искали "возможность IP", то нам бы не подходили фразы "возможность n", т.к. они посвящены более короткой фразе.
Отсекать блоки надо на раннем этапе, до выбора рекомендуемых переводов в блоках/словарях.
"""
import csv  # Standard library for table processing (I/O)
import re  # Standard library for regexp. It used for check author's link

import scrapy
from scrapy import Request  # It's scrapy's request. It used for request for every new URL

# Settings
INPUT_CSV_NAME = 'tables/input.csv'  # Path to input file with csv type
# Delimiter and quotechar are parameters of csv file. You should know it if you created the file
CSV_DELIMITER = '	'
CSV_QUOTECHAR = '"'  # '|'
OUTPUT_CSV_NAME = 'tables/output1.csv'  # Path to output file with csv type
TRANSLATE_WORD_INDEX = 0  # Index of column which should be translated. Others columns will be copied to output file
EXCEPTED_DICTIONARIES = ['разг.']  # Dictionaries which shouldn't be in output
ONLY_RECOMMENDATED_TRANSLATIONS = True  # Flag for selecting only recommended translations


class MultitranSpider(scrapy.Spider):
    name = "multitran"  # It's name of spider which should be used for spider's calling using by 'scrapy crawl nultitran'

    def __init__(self):
        """
        It's the initial method before all calls connected with parsing.
        It's the first method which called after object creating.
        This method includes file opening for input/output (standard files and csv files)
        """
        self.input_file = open(INPUT_CSV_NAME, 'r')
        self.input_reader = csv.reader(self.input_file, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTECHAR,
                                       quoting=csv.QUOTE_ALL)

        self.output_file = open(OUTPUT_CSV_NAME, 'w')
        self.output_writer = csv.writer(self.output_file, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTECHAR,
                                        quoting=csv.QUOTE_ALL)

    def start_requests(self):
        """
        This method is a start point for parsing.
        This method generates requests which will be handled by parse() (is written in Request.callback)
        :return: list of Request
        """
        requests = []  # list which will stores all Requests
        i = 0  # Simple iterator. Enumerate can not be used because the loop includes if clause
        for input_row in self.input_reader:
            if len(input_row) > 0:  # Filter empy rows
                word = input_row[TRANSLATE_WORD_INDEX]  # Word for translating
                # Generates Requests. word is used for URL building.
                # Meta is a service dictionary which can be used in callback. Usually it stores some additional info.
                request = Request("http://www.multitran.com/m.exe?CL=1&s={}&l1=1&l2=2&SHL=2".format(word),
                                  callback=self.parse,
                                  meta={"input_row": input_row, 'index': i})

                requests.append(request)
                i += 1
        return requests

    def write_translations(self, translations, output):
        """
        This method is a post handling. It filters by recommendation system and stores it into output csv file.
        It is called after every block handling.
        :param translations: requested word translation list
        :param output: list of all info for every translation (dictionary, authors, etc.). Translation = [o[1] for o in output], but separate list is more convinient way
        :return: None
        """

        def recommend_translation(translations):
            """
            It's the main method for recommendation system.
            Now the parser calculate recommendation between words from one block.
            The main idea is for every word (unigrams) calculates count of phrases which includes this word.
                After it the method calculates avg by references for every phrase and select phrases with maximum value.
            :param translations: list of different translations of the word.
            :return: indexes of recommended translations from input list
            """

            def calc_value(translate, unigrams):
                words = translate.split()
                return sum([unigrams[w] for w in words]) / len(words)

            # For every word (unigrams) calculates count of references
            unigrams = {}
            for translate in translations:
                for words in translate.split():
                    if unigrams.get(words, None) is None:
                        unigrams[words] = 1
                    else:
                        unigrams[words] += 1

            # For every phrase calculates value based on unigrams's values and find argmax
            maxvalue = 0
            result = []
            for i, translate in enumerate(translations):
                value = calc_value(translate, unigrams)
                if value > maxvalue:
                    maxvalue = value
                    result = [i]

            return result

        recommended_translation_indexes = recommend_translation(translations)
        if ONLY_RECOMMENDATED_TRANSLATIONS:
            # If ONLY_RECOMMENDATED than the parser stores only recommended translations. So it's filtering by precalculated indexes.
            output = [output[i] for i in recommended_translation_indexes]
        else:
            # Else the parser marks translations using 'X' as recommended and 'O' otherwise.
            for i, o in enumerate(output):
                o.append('X' if i in recommended_translation_indexes else 'O')

        # Write ready-to-use data to csv file
        self.output_writer.writerows(output)

    def parse(self, response):
        """
        It's the main handler
        :param response: Scrapy's response
        :return:
        """

        def get_selector_tag(selector):
            """Returns selector tag name"""
            return selector.xpath('name()').extract_first()

        def get_all_leaf_nodes(selector):
            """ Returns all leaf nodes using DFS"""
            all_leaf_xpath = 'descendant-or-self::node()'
            return selector.xpath(all_leaf_xpath)

        common_row_xpath = '//*/tr[child::td[@class="gray" or @class="trans"]]'  # XPath for every row in table
        dict_xpath = 'td[@class="subj"]/a/text()'  # Finds dictionary for every row in table (dictionary for group of translations)
        nx_gramms_сommon_xpath = "//*/div[@class='middle_col'][3]"
        nx_gramms_status_xpath = "p[child::a]/text()"
        nx_gramms_words_xpath = "a[string-length(@title)>0]/text()"
        translate_xpath = 'td[@class="trans"]'

        block_number = 0
        translates = []
        output = []
        for common_row in response.xpath(common_row_xpath):
            dictionary = common_row.xpath(dict_xpath).extract()
            # Check type of row. If the row is translation row than go ahead
            if len(dictionary) > 0:
                if not dictionary[0] in EXCEPTED_DICTIONARIES:  # Check that dictionary is acceptable
                    # Check type of phrase: it can be handled as solid or can be divided on several phrases/words
                    nx_gramms_common = response.xpath(nx_gramms_сommon_xpath)
                    nx_gramms_status = nx_gramms_common.xpath(
                        nx_gramms_status_xpath).extract()  # It's a status of phrase
                    # It generates string for output. It describes parts of phrase or that it is full
                    nx_gramms = 'цельное слово' if len(nx_gramms_status) == 0 else nx_gramms_status[
                                                                                       0] + " : " + "|".join(
                        nx_gramms_common.xpath(nx_gramms_words_xpath).extract())

                    # Some translations can be shown as several parts (gray, some comments in brackets). DFS is solution.
                    # The method finds all leaf text nodes. Concatenation of all nodes's text is translation
                    # All phrases are divided using ';'
                    translation_parts = []  # Translation can be divided on parts (see above). It's list of parts.
                    all_leaf_nodes = get_all_leaf_nodes(common_row.xpath(translate_xpath))
                    comment = ''
                    for node in all_leaf_nodes:
                        flag_full_translation = False
                        node_tag = get_selector_tag(node)
                        if node_tag is None:  # It means that node includes only text
                            node_value = node.extract()
                            # It means that translation is full and let's go to next
                            if node_value.strip() == ";":
                                flag_full_translation = True
                            if node == all_leaf_nodes[-1]:  # Check that node is last
                                translation_parts.append(node_value)
                                flag_full_translation = True
                            if flag_full_translation:
                                translation_value = "".join(translation_parts)

                                try_find_comment = re.findall('(?P<translate_value>.*)\((?P<comment>.*)\)',
                                                              translation_value)
                                if len(try_find_comment) > 0:
                                    translation_value, comment = try_find_comment[0]
                                else:
                                    comment = ''

                                output_array = response.meta['input_row'].copy()
                                output_array.append(translation_value)
                                output_array.append(dictionary[0])
                                output_array.append(str(block_number))
                                output_array.append(block_name)
                                # output_array.append(nx_gramms) It's unused now

                                output_array.append(author)
                                output_array.append(author_href)
                                output_array.append(comment)
                                output_array = [x.strip() for x in output_array]
                                output.append(output_array)

                                translates.append(translation_value)
                                translation_parts = []
                            else:
                                translation_parts.append(node_value)
                        elif node_tag == "a":
                            # Try to finds author's info
                            author_href = node.xpath('@href').extract_first()
                            author = re.findall('/m\.exe\?a=[0-9]*&[amp;]?UserName=(?P<author_name>.*)', author_href)
                            if len(author) > 0:
                                author = author[0]
                            else:
                                author_href = ''
                                author = ''
            # Another variant - the row is a system row which describes new block (name, part of speech etc) (gray background)
            else:
                self.write_translations(translates, output)
                translates = []
                output = []
                block_name = "".join(common_row.xpath('td[@class="gray"]/descendant-or-self::text()').extract())
                block_name = block_name[:block_name.find("|")]
                block_number += 1

        self.write_translations(translates, output)

    # This method will be called after all Requests or after FATAL error.
    # Please, see about loggers and errors https://doc.scrapy.org/en/latest/topics/logging.html
    #
    # So it's some exit point (optional) (empty by default)
    def close(self, reason):
        """
        This method closes input/output files for correct I/O.
        If you doesn't close file, then some data can be lost.

        The method uses standard file closing.
        :param reason: exit status of parsing
        :return: None
        """
        self.input_file.close()
        self.output_file.close()
