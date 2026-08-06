import asyncio
import csv
import os
import random
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


class DivarScraper:
    def __init__(
        self,
        cookies: Dict[str, str],
        headers: Dict[str, str],
        keywords: List[str],
        search_filters: Dict[str, Any],
        links_file: str = "links.txt",
        max_pages: int = 50,
    ):
        self.cookies = cookies
        self.headers = headers
        self.keywords = keywords
        self.search_filters = search_filters
        self.links = self._read_links(links_file)
        self.search_url = self.links[2]
        self.session: Optional[aiohttp.ClientSession] = None
        self.max_pages = max_pages

        self.special_housing: List[Dict[str, str]] = []
        self.district_ads: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    @staticmethod
    def _read_links(fp: str) -> List[str]:
        with open(fp, "r", encoding="utf-8") as f:
            return f.read().strip("\n").split("\n")

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers=self.headers,
            cookies=self.cookies,
            timeout=aiohttp.ClientTimeout(total=30),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def first_request(
        self, pagination_payload: Optional[Dict] = None
    ) -> Dict[str, Any]:
        json_data = {
            "city_ids": ["1"],
            "pagination_data": pagination_payload,
            "disable_recommendation": False,
            "map_state": {"camera_info": {"bbox": {}}},
            "search_data": self.search_filters,
        }
        async with self.session.post(self.search_url, json=json_data) as response:
            response.raise_for_status()
            return await response.json()

    @staticmethod
    def has_next_page(response: Dict[str, Any]) -> bool:
        return (
            response.get("action_log", {})
            .get("server_side_info", {})
            .get("info", {})
            .get("has_next_page", False)
        )

    @staticmethod
    def extract_pagination_data(response: Dict[str, Any]) -> Optional[Dict]:
        """استخراج pagination برای صفحه بعدی"""
        return response.get("pagination", {}).get("data")

    @staticmethod
    def build_url(token: str, ad_instance_id: str) -> str:
        return f"https://api.divar.ir/v8/posts-v2/web/{token}?tracker_session_id={ad_instance_id}"

    async def fetch_json_with_retry(self, url: str) -> Dict[str, Any]:
        while True:
            try:
                async with self.session.get(url) as response:
                    if response.status == 429:
                        sleep_time = random.uniform(60, 150)
                        print(
                            f"!!! Rate limit (429) - Sleeping for {int(sleep_time)}s ..."
                        )
                        await asyncio.sleep(sleep_time)
                        continue
                    response.raise_for_status()
                    return await response.json()
            except Exception as e:
                print(f"Error fetching {url}: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

    def is_agency_text(self, text: str) -> bool:
        return any(keyword in text for keyword in self.keywords)

    @staticmethod
    def extract_text(ad_data: Dict[str, Any]) -> str:
        try:
            return ad_data["sections"][2]["widgets"][1]["data"]["text"]
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def extract_widgets(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return data.get("list_widgets", [])

    @staticmethod
    def extract_post_info(
        widget: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[str]]:
        payload = widget.get("data", {}).get("action", {}).get("payload", {})
        return payload.get("token"), payload.get("ad_instance_id")

    @staticmethod
    def extract_title(data: Dict[str, Any]) -> str:
        try:
            return data["sections"][1]["widgets"][0]["data"]["title"]
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def extract_district(ad_data: Dict[str, Any]) -> str:
        try:
            return (
                ad_data.get("seo", {})
                .get("post_seo_schema", {})
                .get("web_info", {})
                .get("district_persian", "")
            )
        except (KeyError, TypeError):
            return ""

    @staticmethod
    def persian_to_latin(text: str) -> str:
        if not text:
            return "unknown"
        mapping = {
            "ا": "a",
            "آ": "a",
            "ب": "b",
            "پ": "p",
            "ت": "t",
            "ث": "s",
            "ج": "j",
            "چ": "ch",
            "ح": "h",
            "خ": "kh",
            "د": "d",
            "ذ": "z",
            "ر": "r",
            "ز": "z",
            "ژ": "zh",
            "س": "s",
            "ش": "sh",
            "ص": "s",
            "ض": "z",
            "ط": "t",
            "ظ": "z",
            "ع": "a",
            "غ": "gh",
            "ف": "f",
            "ق": "gh",
            "ک": "k",
            "گ": "g",
            "ل": "l",
            "م": "m",
            "ن": "n",
            "و": "v",
            "ه": "h",
            "ی": "i",
            "ئ": "e",
            "۰": "0",
            "۱": "1",
            "۲": "2",
            "۳": "3",
            "۴": "4",
            "۵": "5",
            "۶": "6",
            "۷": "7",
            "۸": "8",
            "۹": "9",
            " ": "_",
            "‌": "",
            "ـ": "",
        }
        result = [mapping.get(char, char) for char in text.strip()]
        latin = "".join(result).lower()
        latin = re.sub(r"[^a-z0-9_]", "", latin)
        latin = re.sub(r"_+", "_", latin).strip("_")
        return latin or "unknown"

    def has_special_housing(self, title: str, text: str) -> bool:
        return "مسکن ویژه" in title or "مسکن ویژه" in text

    async def process_widgets(self, widgets: List[Dict[str, Any]], page: int) -> None:
        for idx, widget in enumerate(widgets):
            token, ad_instance_id = self.extract_post_info(widget)
            if not token or not ad_instance_id:
                continue

            await asyncio.sleep(random.uniform(1, 3))
            ad_data = await self.fetch_json_with_retry(
                self.build_url(token, ad_instance_id)
            )

            text = self.extract_text(ad_data)
            title = self.extract_title(ad_data)
            web_url = ad_data.get("share", {}).get("web_url", "")
            district_persian = self.extract_district(ad_data)
            district_latin = self.persian_to_latin(district_persian)

            if self.is_agency_text(text) or self.is_agency_text(title):
                print(f"[Page {page}][{idx}] {token} -> Skipped (Agency)")
                continue

            row = {
                "token": token,
                "title": title,
                "web_url": web_url,
                "district_persian": district_persian,
                "district_latin": district_latin,
                "text": text[:500],
            }

            if self.has_special_housing(title, text):
                self.special_housing.append(row)
                print(
                    f"[Page {page}][{idx}] {token} -> Special Housing | {district_persian}"
                )
            else:
                self.district_ads[district_latin].append(row)
                print(
                    f"[Page {page}][{idx}] {token} -> {district_persian} ({district_latin})"
                )

    async def run(self) -> None:
        pagination_payload = None
        page = 1

        while page <= self.max_pages:
            print(f"\n========== صفحه {page} ==========")

            try:
                response = await self.first_request(pagination_payload)
            except Exception as e:
                print(f"خطا در دریافت صفحه {page}: {e}")
                break

            widgets = self.extract_widgets(response)
            if not widgets:
                print("هیچ آگهی‌ای پیدا نشد. پایان.")
                break

            await self.process_widgets(widgets, page)

            # چک کردن صفحه بعدی
            has_next = self.has_next_page(response)
            pagination_payload = self.extract_pagination_data(response)

            if not has_next or not pagination_payload:
                print("صفحه بعدی وجود ندارد. پایان.")
                break

            page += 1
            await asyncio.sleep(random.uniform(2, 5))

        self._save_csv_files()

    def _save_csv_files(self) -> None:
        fieldnames = [
            "token",
            "title",
            "web_url",
            "district_persian",
            "district_latin",
            "text",
        ]

        if self.special_housing:
            with open(
                "special_housing.csv", "w", encoding="utf-8-sig", newline=""
            ) as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.special_housing)
            print(
                f"\n✔ special_housing.csv ذخیره شد ({len(self.special_housing)} آگهی)"
            )

        if self.district_ads:
            os.makedirs("districts", exist_ok=True)
            for district, rows in self.district_ads.items():
                filepath = os.path.join("districts", f"{district}.csv")
                with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"✔ districts/{district}.csv ذخیره شد ({len(rows)} آگهی)")


# ==================== تنظیمات ====================

COOKIES = {
    "did": "b030689c-3d42-4a2e-a811-883e88c9c422",
    "cdid": "ac500cf5-e04b-4cb9-aa5b-d86d098e1db9",
    "multi-city": "tehran%7C",
    "city": "tehran",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
}

REAL_ESTATE_KEYWORDS = [
    "املاک",
    "مشاور املاک",
    "مشاورین املاک",
    "بنگاه",
    "بنگاه املاک",
    "دفتر املاک",
    "دفتر معاملات",
    "آژانس املاک",
    "آژانس مسکن",
    "دفتر فروش",
    "کارشناس فروش",
    "کارشناس املاک",
    "ملکی",
    "فایل",
    "فایلینگ",
    "فایل اختصاصی",
    "فایل ویژه",
    "واحد فایل",
    "پرونده فروش",
    "مشاور",
    "کارشناس",
    "تماس بگیرید",
    "فقط تماس",
    "همکاران",
    "همکار محترم",
    "همکار املاک",
    "بازدید",
    "هماهنگی",
    "هماهنگی بازدید",
    "بازدید رایگان",
    "هماهنگ کنید",
    "معامله",
    "سرمایه گذاری",
    "سرمایه‌گذاری",
    "سرمایه گذار",
    "فرصت سرمایه گذاری",
    "فرصت استثنایی",
    "فرصت طلایی",
    "فرصت ویژه",
    "فول امکانات",
    "لاکچری",
    "لوکس",
    "فوق العاده",
    "فوق‌العاده",
    "نوساز",
    "کلید نخورده",
    "بازسازی شده",
    "بازسازی‌شده",
    "فایل خاص",
    "فایل VIP",
    "vip",
    "وی آی پی",
    "اختصاصی",
    "اکازیون",
    "اکازیون واقعی",
    "فوری",
    "زیر قیمت",
    "قیمت مناسب",
    "بدون مشابه",
    "سند",
    "سند تک برگ",
    "تک برگ",
    "قولنامه",
    "سند شش دانگ",
    "شش دانگ",
    "وکالتی",
    "پایان کار",
    "مشاور پاسخگو",
    "۲۴ ساعته",
    "۲۴ساعته",
    "ثبت رایگان",
    "سپردن ملک",
    "سپردن فایل",
    "خرید و فروش",
    "رهن و اجاره",
    "اجاره و فروش",
    "فروشنده واقعی",
    "مالک فروشنده",
    "همه فایل ها",
    "همه فایل‌ها",
    "بیش از",
    "صدها فایل",
    "بانک فایل",
    "بانک اطلاعاتی",
    "آماده قرارداد",
    "قرارداد رسمی",
    "ملک شما",
    "ثبت ملک",
    "مسکن",
    "هم خونه",
    "همخونه",
    "همخانه",
]

SEARCH_FILTERS = {
    "form_data": {
        "data": {
            "business-type": {"repeated_string": {"value": ["personal"]}},
            "category": {"str": {"value": "residential-rent"}},
            "districts": {
                "repeated_string": {
                    "value": [
                        "178",
                        "4148",
                        "4177",
                        "4184",
                        "4179",
                        "4178",
                        "179",
                        "175",
                        "910",
                        "4177",
                    ]
                }
            },
        }
    },
    "server_payload": {
        "@type": "type.googleapis.com/widgets.SearchData.ServerPayload",
        "additional_form_data": {"data": {"sort": {"str": {"value": "sort_date"}}}},
    },
}


async def main():
    async with DivarScraper(
        cookies=COOKIES,
        headers=HEADERS,
        keywords=REAL_ESTATE_KEYWORDS,
        search_filters=SEARCH_FILTERS,
        links_file="links.txt",
        max_pages=50,
    ) as scraper:
        await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())
