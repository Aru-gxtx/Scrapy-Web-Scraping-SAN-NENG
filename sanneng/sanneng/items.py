# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class SannengItem(scrapy.Item):
    name = scrapy.Field()
    price = scrapy.Field()
    sold = scrapy.Field()
    shop_name = scrapy.Field()
    shop_location = scrapy.Field()
    product_url = scrapy.Field()
    image_url = scrapy.Field()
    rating = scrapy.Field()


class TokopediaItem(scrapy.Item):
    name = scrapy.Field()
    price = scrapy.Field()
    sold = scrapy.Field()
    shop_name = scrapy.Field()
    shop_location = scrapy.Field()
    product_url = scrapy.Field()
    image_url = scrapy.Field()
    rating = scrapy.Field()
    description = scrapy.Field()
    detail_image_urls = scrapy.Field()
