import time
from urllib.parse import urlencode

import scrapy
from curl_cffi import requests as cffi_requests

from sanneng.items import TokopediaItem

_GQL_URL = "https://gql.tokopedia.com/"
_GQL_HEADERS = {
    "Content-Type": "application/json",
    "x-device": "desktop-0.0",
    "Referer": "https://www.tokopedia.com/search?q=Sanneng&st=product",
    "Origin": "https://www.tokopedia.com",
}
_SEARCH_QUERY = (
    "query SearchProductV5Query($params:String!){"
    "searchProductV5(params:$params){"
    "header{totalData responseCode keywordProcess}"
    "data{products{"
    "name url applink"
    " mediaURL{image image300}"
    " shop{name url city tier}"
    " price{text number range original discountPercentage}"
    " rating wishlist"
    " labelGroups{position title type url}"
    " category{name breadcrumb}"
    "}}}}"
)
_ROWS_PER_PAGE = 60


class TokopediaSpider(scrapy.Spider):
    name = "tokopedia"

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "ITEM_PIPELINES": {},  # disable Scrapy pipelines – we write JSON ourselves
        "FEEDS": {
            "tokopedia.json": {
                "format": "json",
                "encoding": "utf8",
                "overwrite": True,
                "indent": 2,
            }
        },
    }

    async def start(self):
        session = cffi_requests.Session(impersonate="chrome124")
        # Establish Akamai session by loading the search page
        session.get(
            "https://www.tokopedia.com/search?q=Sanneng&st=product",
            timeout=30,
        )

        max_pages = int(getattr(self, "max_pages", 0) or 0)
        page = 1
        total_scraped = 0

        while True:
            if max_pages and page > max_pages:
                break

            params_str = urlencode({
                "q": "Sanneng",
                "st": "product",
                "page": str(page),
                "rows": str(_ROWS_PER_PAGE),
                "start": str((page - 1) * _ROWS_PER_PAGE),
                "source": "search",
                "device": "desktop",
                "scheme": "https",
                "navsource": "",
                "srp_component_id": "02.01.00.00",
                "srp_page_id": "",
                "srp_page_title": "",
            })

            payload = [{
                "operationName": "SearchProductV5Query",
                "query": _SEARCH_QUERY,
                "variables": {"params": params_str},
            }]

            try:
                resp = session.post(
                    _GQL_URL, json=payload, headers=_GQL_HEADERS, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                self.logger.error("GQL request failed on page %d: %s", page, exc)
                break

            srp = data[0].get("data", {}).get("searchProductV5", {})
            total_data = srp.get("header", {}).get("totalData", 0)
            products = srp.get("data", {}).get("products") or []

            self.logger.info(
                "Page %d: got %d products (total available: %d)",
                page, len(products), total_data,
            )

            if not products:
                break

            for p in products:
                item = TokopediaItem()
                item["name"] = p.get("name", "")
                item["product_url"] = p.get("url", "")
                item["price"] = p.get("price", {}).get("text", "")
                item["image_url"] = p.get("mediaURL", {}).get("image300") or p.get("mediaURL", {}).get("image", "")
                item["rating"] = p.get("rating", "")
                item["shop_name"] = p.get("shop", {}).get("name", "")
                item["shop_location"] = p.get("shop", {}).get("city", "")
                item["sold"] = self._extract_sold(p.get("labelGroups") or [])
                item["description"] = ""
                item["detail_image_urls"] = []
                yield item
                total_scraped += 1

            if total_scraped >= total_data or len(products) < _ROWS_PER_PAGE:
                break

            page += 1
            time.sleep(1)

    @staticmethod
    def _extract_sold(label_groups):
        for label in label_groups:
            if label.get("position") == "ri_product_credibility":
                return label.get("title", "")
        return ""


