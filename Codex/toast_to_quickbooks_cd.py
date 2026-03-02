"""
=============================================================================
TOAST POS → QUICKBOOKS DESKTOP ENTERPRISE
Đồng bộ doanh thu bán hàng hàng ngày (Journal Entries)
=============================================================================

Kiến trúc:
    Toast REST API  →  Python Script  →  QuickBooks Desktop (COM/QBXML)

Yêu cầu:
    - Windows OS (cùng máy với QuickBooks Desktop Enterprise)
    - Python 32-bit (nếu QB phiên bản trước 2022) hoặc 64-bit (QB 2022+)
    - pip install pywin32 requests schedule
    - QuickBooks Desktop Enterprise đang mở (hoặc chạy nền)
    - Toast API credentials (Standard API Access - miễn phí)

Tác giả: Tự động tạo bởi Claude
Ngày: 2026-02-26
=============================================================================
"""

import win32com.client
import requests
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import xml.etree.ElementTree as ET
import time
import schedule

# =============================================================================
# CẤU HÌNH - CHỈNH SỬA FILE config.json TRƯỚC KHI CHẠY
# =============================================================================

CONFIG_FILE = Path(__file__).parent / "config.json"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"sync_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ToastToQB")


def load_config() -> dict:
    """Đọc cấu hình từ config.json"""
    if not CONFIG_FILE.exists():
        logger.error(f"Không tìm thấy file cấu hình: {CONFIG_FILE}")
        logger.error("Hãy tạo file config.json theo mẫu config.example.json")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# PHẦN 1: TOAST API CLIENT
# =============================================================================

class ToastAPIClient:
    """
    Client kết nối Toast POS API để lấy dữ liệu bán hàng.
    
    Cách lấy credentials:
        1. Đăng nhập Toast Web (backend)
        2. Vào Integrations > Toast API access > Manage credentials
        3. Tạo Standard API credentials
        4. Ghi lại Client ID, Client Secret, Restaurant GUID
    """

    def __init__(self, config: dict):
        self.client_id = config["toast"]["client_id"]
        self.client_secret = config["toast"]["client_secret"]
        self.restaurant_guid = config["toast"]["restaurant_guid"]
        self.api_hostname = config["toast"].get("api_hostname", "https://ws-api.toasttab.com")
        self.access_token = None
        self.token_expiry = None

    def authenticate(self):
        """Xác thực và lấy access token từ Toast API (OAuth 2.0)"""
        url = f"{self.api_hostname}/authentication/v1/authentication/login"
        payload = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "userAccessType": "TOAST_MACHINE_CLIENT",
        }
        headers = {"Content-Type": "application/json"}

        logger.info("Đang xác thực với Toast API...")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        # Token nằm trong data["token"]["accessToken"]
        token_data = data.get("token", data)
        self.access_token = token_data.get("accessToken", token_data.get("access_token"))
        
        # Token thường hết hạn sau vài giờ
        expires_in = token_data.get("expiresIn", token_data.get("expires_in", 3600))
        self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)

        logger.info("Xác thực Toast API thành công!")

    def _ensure_authenticated(self):
        """Đảm bảo token còn hiệu lực"""
        if not self.access_token or datetime.now() >= self.token_expiry:
            self.authenticate()

    def _get_headers(self) -> dict:
        """Headers cho mỗi API request"""
        self._ensure_authenticated()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Toast-Restaurant-External-ID": self.restaurant_guid,
            "Content-Type": "application/json",
        }

    def get_orders(self, business_date: str) -> list:
        """
        Lấy tất cả đơn hàng của một ngày kinh doanh.
        
        Args:
            business_date: Ngày kinh doanh, format "yyyyMMdd" (VD: "20260225")
        
        Returns:
            Danh sách các đơn hàng (Order objects)
        """
        url = f"{self.api_hostname}/orders/v2/ordersBulk"
        all_orders = []
        page = 1
        page_size = 100

        while True:
            params = {
                "businessDate": business_date,
                "pageSize": page_size,
                "page": page,
            }
            logger.info(f"Lấy đơn hàng ngày {business_date}, trang {page}...")
            response = requests.get(
                url, headers=self._get_headers(), params=params, timeout=60
            )
            response.raise_for_status()
            orders = response.json()

            if not orders:
                break

            all_orders.extend(orders)
            
            # Kiểm tra pagination
            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            page += 1

        logger.info(f"Tổng cộng {len(all_orders)} đơn hàng ngày {business_date}")
        return all_orders

    def get_cash_management_deposits(self, business_date: str) -> list:
        """
        Lấy thông tin tiền gửi/rút tiền mặt.
        
        Args:
            business_date: Format "yyyyMMdd"
        """
        url = f"{self.api_hostname}/cashmgmt/v1/entries"
        params = {"businessDate": business_date}

        try:
            response = requests.get(
                url, headers=self._get_headers(), params=params, timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Không lấy được cash management data: {e}")
            return []

    # -----------------------------------------------------------------
    # Menu & Dining Option cache  (gọi 1 lần/ngày, dùng lại khi aggregate)
    # -----------------------------------------------------------------

    def get_menu_groups(self) -> dict:
        """
        Lấy danh sách MenuGroup từ config API.
        Trả về dict  { guid: group_name }
        VD: {"1c6187fa-...": "Food", "500feeaa-...": "Bar"}
        """
        url = f"{self.api_hostname}/config/v2/menuGroups"
        logger.info("Lấy danh sách MenuGroup từ Toast...")
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=60)
            resp.raise_for_status()
            return {g["guid"]: g.get("name", "Unknown") for g in resp.json()}
        except Exception as e:
            logger.warning(f"Không lấy được MenuGroup: {e}")
            return {}

    def get_dining_options(self) -> dict:
        """
        Lấy danh sách DiningOption từ config API.
        Trả về dict  { guid: option_name }
        VD: {"23fc...": "Dine In", "b1b1...": "Delivery"}
        """
        url = f"{self.api_hostname}/config/v2/diningOptions"
        logger.info("Lấy danh sách DiningOption từ Toast...")
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=60)
            resp.raise_for_status()
            return {d["guid"]: d.get("name", "Unknown") for d in resp.json()}
        except Exception as e:
            logger.warning(f"Không lấy được DiningOption: {e}")
            return {}

    def get_revenue_centers(self) -> dict:
        """
        Lấy danh sách RevenueCenter.
        Trả về dict  { guid: center_name }
        """
        url = f"{self.api_hostname}/config/v2/revenueCenters"
        logger.info("Lấy danh sách RevenueCenter từ Toast...")
        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=60)
            resp.raise_for_status()
            return {r["guid"]: r.get("name", "Unknown") for r in resp.json()}
        except Exception as e:
            logger.warning(f"Không lấy được RevenueCenter: {e}")
            return {}

    # -----------------------------------------------------------------
    # Aggregate v2 – tách theo sales_category + order source/channel
    # -----------------------------------------------------------------

    def aggregate_daily_sales(
        self,
        orders: list,
        menu_groups: dict | None = None,
        dining_options: dict | None = None,
        revenue_centers: dict | None = None,
        category_rules: dict | None = None,
    ) -> dict:
        """
        Tổng hợp dữ liệu bán hàng, **tách theo sales category & order source**.

        Cách phân loại doanh thu (sales_by_category):
          - Mỗi selection có itemGroup.guid → tra menu_groups → group name
          - group name được map vào category nhờ category_rules trong config
          - VD: group "Appetizers", "Entrees", "Desserts" → category "food"
                group "Beer", "Wine", "Cocktails"        → category "bar"
          - Nếu không match rule nào → category "other"

        Cách phân loại theo kênh bán (sales_by_source):
          - order.source chứa giá trị như "In Store", "API", "Online",
            "Grubhub", "DoorDash", "Uber Eats", v.v.
          - Hoặc dùng order.diningOption → tra dining_options → tên
          - Config có source_rules để map source/diningOption → channel key

        Returns:
            dict giống bản cũ + thêm:
              "sales_by_category": {"food": Decimal, "bar": Decimal, ...}
              "sales_by_source":   {"in_store": Decimal, "doordash": Decimal, ...}
        """
        if menu_groups is None:
            menu_groups = {}
        if dining_options is None:
            dining_options = {}
        if revenue_centers is None:
            revenue_centers = {}
        if category_rules is None:
            category_rules = {}

        summary = {
            "gross_sales": Decimal("0"),
            "discounts": Decimal("0"),
            "tax": Decimal("0"),
            "tips": Decimal("0"),
            "cash_payments": Decimal("0"),
            "credit_card_payments": Decimal("0"),
            "gift_card_payments": Decimal("0"),
            "other_payments": Decimal("0"),
            "service_charges": Decimal("0"),
            "refunds": Decimal("0"),
            "net_sales": Decimal("0"),
            "order_count": 0,
            # ---- MỚI ----
            "sales_by_category": {},   # {"food": Decimal, "bar": Decimal, ...}
            "sales_by_source": {},     # {"in_store": Decimal, "doordash": Decimal, ...}
            "by_revenue_center": {},
        }

        # Hàm helper: tra tên group → category key
        group_to_cat = category_rules.get("menu_group_to_category", {})
        source_to_channel = category_rules.get("source_to_channel", {})
        default_category = category_rules.get("default_category", "other")
        default_channel = category_rules.get("default_channel", "in_store")

        def _resolve_category(item_group_guid: str) -> str:
            group_name = menu_groups.get(item_group_guid, "").lower()
            # Tìm trong mapping  (key = substring match)
            for pattern, cat in group_to_cat.items():
                if pattern.lower() in group_name:
                    return cat
            return default_category

        def _resolve_channel(order: dict) -> str:
            # Ưu tiên 1: source (VD "Grubhub", "DoorDash", "Uber Eats")
            source = (order.get("source") or "").strip()
            source_lower = source.lower()
            for pattern, ch in source_to_channel.items():
                if pattern.lower() in source_lower:
                    return ch
            # Ưu tiên 2: diningOption name
            do_guid = (order.get("diningOption") or {}).get("guid", "")
            do_name = dining_options.get(do_guid, "").lower()
            for pattern, ch in source_to_channel.items():
                if pattern.lower() in do_name:
                    return ch
            return default_channel

        for order in orders:
            if order.get("voided") or order.get("deleted"):
                continue

            summary["order_count"] += 1
            channel = _resolve_channel(order)

            # Revenue center
            rc_guid = (order.get("revenueCenter") or {}).get("guid", "")
            rc_name = revenue_centers.get(rc_guid, rc_guid) if rc_guid else ""

            for check in order.get("checks", []):
                if check.get("voided") or check.get("deleted"):
                    continue

                tax_amount = Decimal(str(check.get("taxAmount", 0)))
                summary["tax"] += tax_amount

                # --- Selection-level breakdown ---
                for sel in check.get("selections", []):
                    if sel.get("voided"):
                        continue
                    price = Decimal(str(sel.get("price", 0)))
                    qty = int(sel.get("quantity", 1))
                    pre_discount = Decimal(str(sel.get("preDiscountPrice", price)))
                    line_total = pre_discount  # preDiscountPrice đã nhân qty

                    ig_guid = (sel.get("itemGroup") or {}).get("guid", "")
                    cat = _resolve_category(ig_guid)

                    # Cộng vào category
                    summary["sales_by_category"].setdefault(cat, Decimal("0"))
                    summary["sales_by_category"][cat] += line_total

                    # Cộng vào source/channel
                    summary["sales_by_source"].setdefault(channel, Decimal("0"))
                    summary["sales_by_source"][channel] += line_total

                    # Revenue center
                    if rc_name:
                        summary["by_revenue_center"].setdefault(rc_name, Decimal("0"))
                        summary["by_revenue_center"][rc_name] += line_total

                    summary["gross_sales"] += line_total

                # --- Check-level: discounts ---
                for ad in check.get("appliedDiscounts", []):
                    summary["discounts"] += Decimal(str(ad.get("discountAmount", 0)))

                # --- Check-level: payments ---
                for payment in check.get("payments", []):
                    if payment.get("voidInfo"):
                        continue
                    pay_amount = Decimal(str(payment.get("amount", 0)))
                    tip_amount = Decimal(str(payment.get("tipAmount", 0)))
                    pay_type = (payment.get("type") or "").upper()

                    summary["tips"] += tip_amount

                    if pay_type == "CASH":
                        summary["cash_payments"] += pay_amount
                    elif pay_type in ("CREDIT", "CREDIT_CARD"):
                        summary["credit_card_payments"] += pay_amount
                    elif pay_type in ("GIFTCARD", "GIFT_CARD"):
                        summary["gift_card_payments"] += pay_amount
                    elif pay_type == "REFUND":
                        summary["refunds"] += pay_amount
                    else:
                        summary["other_payments"] += pay_amount

                # --- Check-level: service charges ---
                for sc in check.get("appliedServiceCharges", []):
                    summary["service_charges"] += Decimal(str(sc.get("chargeAmount", 0)))

        summary["net_sales"] = summary["gross_sales"] - summary["discounts"]

        # Làm tròn tất cả Decimal
        def _round(d):
            return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        for key in list(summary.keys()):
            val = summary[key]
            if isinstance(val, Decimal):
                summary[key] = _round(val)
            elif isinstance(val, dict):
                summary[key] = {k: _round(v) for k, v in val.items() if isinstance(v, Decimal)}

        return summary


# =============================================================================
# PHẦN 2: QUICKBOOKS DESKTOP CLIENT (COM / QBXML)
# =============================================================================

class QuickBooksDesktopClient:
    """
    Client kết nối QuickBooks Desktop Enterprise qua COM (QBXMLRP2).
    
    QBXMLRP2 là COM object có sẵn khi cài QuickBooks Desktop.
    Không cần cài thêm SDK nào.
    
    Lưu ý quan trọng:
        - QuickBooks Desktop phải đang mở (hoặc dịch vụ đang chạy)
        - Lần đầu chạy: QB sẽ hỏi quyền truy cập → Chọn "Yes, always"
        - Python phải cùng kiến trúc (32/64-bit) với QuickBooks
    """

    def __init__(self, config: dict):
        self.app_name = config["quickbooks"].get("app_name", "ToastSync")
        self.company_file = config["quickbooks"].get("company_file", "")
        self.qbxml_version = config["quickbooks"].get("qbxml_version", "13.0")
        self.request_processor = None

    def connect(self):
        """Kết nối đến QuickBooks Desktop qua COM"""
        logger.info("Đang kết nối QuickBooks Desktop...")
        try:
            self.request_processor = win32com.client.Dispatch("QBXMLRP2.RequestProcessor")
            self.request_processor.OpenConnection2(
                "",  # Connection ID (tự động)
                self.app_name,
                1,  # localQBD connection type
            )
            logger.info("Kết nối QuickBooks Desktop thành công!")
        except Exception as e:
            logger.error(f"Không thể kết nối QuickBooks Desktop: {e}")
            logger.error(
                "Đảm bảo:\n"
                "  1. QuickBooks Desktop đang mở\n"
                "  2. Python cùng kiến trúc (32/64-bit) với QuickBooks\n"
                "  3. Chạy script với quyền admin nếu lần đầu"
            )
            raise

    def disconnect(self):
        """Ngắt kết nối QuickBooks"""
        if self.request_processor:
            try:
                self.request_processor.CloseConnection()
                logger.info("Đã ngắt kết nối QuickBooks Desktop")
            except Exception as e:
                logger.warning(f"Lỗi khi ngắt kết nối: {e}")

    def _send_request(self, qbxml_request: str) -> str:
        """
        Gửi QBXML request đến QuickBooks và nhận response.
        
        Args:
            qbxml_request: Chuỗi XML theo chuẩn QBXML
            
        Returns:
            QBXML response string
        """
        ticket = self.request_processor.BeginSession(self.company_file, 0)
        try:
            response = self.request_processor.ProcessRequest(ticket, qbxml_request)
            return response
        finally:
            self.request_processor.EndSession(ticket)

    def _parse_response(self, response_xml: str) -> dict:
        """Parse QBXML response và kiểm tra lỗi"""
        root = ET.fromstring(response_xml)
        
        # Tìm response element
        msgs_rs = root.find(".//QBXMLMsgsRs")
        if msgs_rs is None:
            return {"status_code": "-1", "status_message": "Không tìm thấy QBXMLMsgsRs"}

        # Lấy element response đầu tiên
        for child in msgs_rs:
            status_code = child.get("statusCode", "-1")
            status_message = child.get("statusMessage", "Unknown")
            status_severity = child.get("statusSeverity", "Error")

            return {
                "status_code": status_code,
                "status_message": status_message,
                "status_severity": status_severity,
                "element": child,
            }

        return {"status_code": "-1", "status_message": "Response rỗng"}

    def query_accounts(self) -> list:
        """
        Lấy danh sách tài khoản (Chart of Accounts) từ QuickBooks.
        Dùng để mapping accounts khi cấu hình.
        """
        qbxml = f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{self.qbxml_version}"?>
<QBXML>
    <QBXMLMsgsRq onError="stopOnError">
        <AccountQueryRq requestID="1">
        </AccountQueryRq>
    </QBXMLMsgsRq>
</QBXML>"""

        response = self._send_request(qbxml)
        result = self._parse_response(response)

        accounts = []
        if result["status_code"] == "0" and result.get("element") is not None:
            for acct_ret in result["element"].findall("AccountRet"):
                accounts.append({
                    "list_id": acct_ret.findtext("ListID", ""),
                    "full_name": acct_ret.findtext("FullName", ""),
                    "account_type": acct_ret.findtext("AccountType", ""),
                    "account_number": acct_ret.findtext("AccountNumber", ""),
                    "is_active": acct_ret.findtext("IsActive", "true"),
                })
        return accounts

    def create_journal_entry(
        self,
        txn_date: str,
        ref_number: str,
        memo: str,
        lines: list,
    ) -> dict:
        """
        Tạo Journal Entry trong QuickBooks Desktop.
        
        Args:
            txn_date: Ngày giao dịch, format "YYYY-MM-DD"
            ref_number: Số tham chiếu (VD: "TOAST-20260225")
            memo: Ghi chú
            lines: Danh sách các dòng, mỗi dòng là dict:
                {
                    "type": "debit" hoặc "credit",
                    "account_name": "Tên tài khoản trong QB",
                    "amount": Decimal("100.00"),
                    "memo": "Ghi chú dòng" (tùy chọn),
                    "entity_name": "Tên khách hàng/vendor" (tùy chọn)
                }
        
        Returns:
            dict với status và thông tin transaction
        """
        # Xây dựng QBXML cho JournalEntryAdd
        lines_xml = ""
        for line in lines:
            if line["amount"] <= 0:
                continue

            amount_str = str(line["amount"].quantize(Decimal("0.01")))
            line_memo = line.get("memo", memo)

            if line["type"].lower() == "debit":
                lines_xml += f"""
            <JournalDebitLine>
                <AccountRef>
                    <FullName>{self._escape_xml(line['account_name'])}</FullName>
                </AccountRef>
                <Amount>{amount_str}</Amount>
                <Memo>{self._escape_xml(line_memo)}</Memo>
            </JournalDebitLine>"""
            else:
                lines_xml += f"""
            <JournalCreditLine>
                <AccountRef>
                    <FullName>{self._escape_xml(line['account_name'])}</FullName>
                </AccountRef>
                <Amount>{amount_str}</Amount>
                <Memo>{self._escape_xml(line_memo)}</Memo>
            </JournalCreditLine>"""

        qbxml = f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{self.qbxml_version}"?>
<QBXML>
    <QBXMLMsgsRq onError="stopOnError">
        <JournalEntryAddRq requestID="1">
            <JournalEntryAdd>
                <TxnDate>{txn_date}</TxnDate>
                <RefNumber>{self._escape_xml(ref_number)}</RefNumber>
                <Memo>{self._escape_xml(memo)}</Memo>{lines_xml}
            </JournalEntryAdd>
        </JournalEntryAddRq>
    </QBXMLMsgsRq>
</QBXML>"""

        logger.info(f"Tạo Journal Entry: {ref_number} ngày {txn_date}")
        logger.debug(f"QBXML Request:\n{qbxml}")

        response = self._send_request(qbxml)
        result = self._parse_response(response)

        if result["status_code"] == "0":
            txn_id = ""
            if result.get("element") is not None:
                je_ret = result["element"].find("JournalEntryRet")
                if je_ret is not None:
                    txn_id = je_ret.findtext("TxnID", "")
            logger.info(f"✅ Journal Entry tạo thành công! TxnID: {txn_id}")
            return {"success": True, "txn_id": txn_id, "message": result["status_message"]}
        else:
            logger.error(
                f"❌ Lỗi tạo Journal Entry: [{result['status_code']}] {result['status_message']}"
            )
            return {
                "success": False,
                "error_code": result["status_code"],
                "message": result["status_message"],
            }

    def check_journal_entry_exists(self, ref_number: str) -> bool:
        """Kiểm tra Journal Entry đã tồn tại chưa (tránh duplicate)"""
        qbxml = f"""<?xml version="1.0" encoding="utf-8"?>
<?qbxml version="{self.qbxml_version}"?>
<QBXML>
    <QBXMLMsgsRq onError="stopOnError">
        <JournalEntryQueryRq requestID="1">
            <RefNumber>{self._escape_xml(ref_number)}</RefNumber>
        </JournalEntryQueryRq>
    </QBXMLMsgsRq>
</QBXML>"""

        response = self._send_request(qbxml)
        result = self._parse_response(response)

        # statusCode "0" = tìm thấy, "1" = không tìm thấy (nhưng không lỗi)
        if result["status_code"] == "0":
            return True
        return False

    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape ký tự đặc biệt trong XML"""
        if not text:
            return ""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )


# =============================================================================
# PHẦN 3: ĐỒNG BỘ DỮ LIỆU (SYNC ENGINE)
# =============================================================================

class ToastQBSyncEngine:
    """
    Engine đồng bộ dữ liệu bán hàng từ Toast sang QuickBooks Desktop.
    
    Quy trình:
        1. Lấy đơn hàng từ Toast API
        2. Tổng hợp thành báo cáo doanh thu ngày
        3. Map sang các tài khoản trong QuickBooks (Chart of Accounts)
        4. Tạo Journal Entry trong QuickBooks
    """

    def __init__(self, config: dict):
        self.config = config
        self.toast = ToastAPIClient(config)
        self.qb = QuickBooksDesktopClient(config)
        
        # Account mapping từ config
        self.account_map = config.get("account_mapping", {})
        # Category/source classification rules
        self.category_rules = config.get("category_rules", {})
        # Caches (populated once per run)
        self._menu_groups = None
        self._dining_options = None
        self._revenue_centers = None

    def _ensure_caches(self):
        """Fetch menu_groups, dining_options, revenue_centers một lần."""
        if self._menu_groups is None:
            self._menu_groups = self.toast.get_menu_groups()
        if self._dining_options is None:
            self._dining_options = self.toast.get_dining_options()
        if self._revenue_centers is None:
            self._revenue_centers = self.toast.get_revenue_centers()

    def sync_date(self, date: datetime) -> dict:
        """
        Đồng bộ dữ liệu bán hàng cho một ngày cụ thể.
        
        Args:
            date: Ngày cần đồng bộ
            
        Returns:
            dict với kết quả đồng bộ
        """
        date_str = date.strftime("%Y%m%d")  # Toast format
        date_display = date.strftime("%Y-%m-%d")  # QB format
        ref_number = f"TOAST-{date_str}"

        logger.info(f"{'='*60}")
        logger.info(f"BẮT ĐẦU ĐỒNG BỘ NGÀY: {date_display}")
        logger.info(f"{'='*60}")

        # Bước 0: Kiểm tra đã đồng bộ chưa
        try:
            self.qb.connect()
            if self.qb.check_journal_entry_exists(ref_number):
                logger.warning(f"⚠️  Journal Entry '{ref_number}' đã tồn tại. Bỏ qua.")
                return {"success": True, "skipped": True, "message": "Đã đồng bộ trước đó"}
        except Exception as e:
            logger.error(f"Lỗi kết nối QuickBooks: {e}")
            return {"success": False, "message": str(e)}
        finally:
            self.qb.disconnect()

        # Bước 1: Lấy dữ liệu từ Toast
        try:
            orders = self.toast.get_orders(date_str)
            if not orders:
                logger.info(f"Không có đơn hàng ngày {date_display}")
                return {"success": True, "skipped": True, "message": "Không có đơn hàng"}
        except Exception as e:
            logger.error(f"Lỗi lấy dữ liệu Toast: {e}")
            return {"success": False, "message": f"Toast API error: {e}"}

        # Bước 2: Tổng hợp doanh thu (với phân loại category & source)
        self._ensure_caches()
        summary = self.toast.aggregate_daily_sales(
            orders,
            menu_groups=self._menu_groups,
            dining_options=self._dining_options,
            revenue_centers=self._revenue_centers,
            category_rules=self.category_rules,
        )
        self._log_summary(date_display, summary)

        # Bước 3: Tạo Journal Entry lines
        lines = self._build_journal_lines(summary)
        
        # Kiểm tra cân bằng debit = credit
        total_debit = sum(l["amount"] for l in lines if l["type"] == "debit")
        total_credit = sum(l["amount"] for l in lines if l["type"] == "credit")
        
        if total_debit != total_credit:
            diff = total_debit - total_credit
            logger.error(
                f"❌ Journal Entry KHÔNG CÂN BẰNG! "
                f"Debit={total_debit}, Credit={total_credit}, Chênh lệch={diff}"
            )
            # Thêm dòng điều chỉnh
            if diff > 0:
                lines.append({
                    "type": "credit",
                    "account_name": self.account_map.get("rounding", "Other Income"),
                    "amount": abs(diff),
                    "memo": "Làm tròn Toast",
                })
            else:
                lines.append({
                    "type": "debit",
                    "account_name": self.account_map.get("rounding", "Other Expense"),
                    "amount": abs(diff),
                    "memo": "Làm tròn Toast",
                })
            logger.info("Đã thêm dòng điều chỉnh làm tròn")

        # Bước 4: Gửi Journal Entry vào QuickBooks
        memo = f"Toast POS Sales - {date_display} ({summary['order_count']} orders)"
        
        try:
            self.qb.connect()
            result = self.qb.create_journal_entry(
                txn_date=date_display,
                ref_number=ref_number,
                memo=memo,
                lines=lines,
            )
            return result
        except Exception as e:
            logger.error(f"Lỗi tạo Journal Entry: {e}")
            return {"success": False, "message": str(e)}
        finally:
            self.qb.disconnect()

    def _build_journal_lines(self, summary: dict) -> list:
        """
        Chuyển đổi báo cáo doanh thu thành các dòng Journal Entry.
        
        DEBIT (Nợ):
            - Cash / CC / Gift Card / Other (theo phương thức thanh toán)
            - Discounts (contra revenue)
        
        CREDIT (Có):
            - Doanh thu **tách theo category** (food, bar, …)
            - Doanh thu **tách theo kênh delivery** (doordash, uber, grubhub, …)
            - Sales Tax Payable / Tips Payable / Service Charges
        
        Logic:
          Nếu config có "category_account_map" → credit mỗi category riêng.
          Nếu không → fallback về 1 tài khoản sales_revenue gộp (backward-compat).
        """
        am = self.account_map
        cat_map = am.get("category_account_map", {})   # {"food": "Food Sales", "bar": "Bar Sales", …}
        src_map = am.get("source_account_map", {})      # {"doordash": "DoorDash Revenue", …}
        lines = []

        # === DEBIT LINES ===

        if summary["cash_payments"] > 0:
            lines.append({
                "type": "debit",
                "account_name": am.get("cash", "Cash in Drawer"),
                "amount": summary["cash_payments"],
                "memo": "Cash payments from Toast",
            })

        if summary["credit_card_payments"] > 0:
            lines.append({
                "type": "debit",
                "account_name": am.get("credit_card_receivable", "Accounts Receivable"),
                "amount": summary["credit_card_payments"],
                "memo": "Credit card payments from Toast",
            })

        if summary["gift_card_payments"] > 0:
            lines.append({
                "type": "debit",
                "account_name": am.get("gift_card_receivable", "Gift Card Receivable"),
                "amount": summary["gift_card_payments"],
                "memo": "Gift card payments from Toast",
            })

        if summary["other_payments"] > 0:
            lines.append({
                "type": "debit",
                "account_name": am.get("other_payments", "Other Receivable"),
                "amount": summary["other_payments"],
                "memo": "Other payments from Toast",
            })

        if summary["discounts"] > 0:
            lines.append({
                "type": "debit",
                "account_name": am.get("discounts", "Discounts Given"),
                "amount": summary["discounts"],
                "memo": "Discounts from Toast",
            })

        if summary["refunds"] > 0:
            lines.append({
                "type": "credit",
                "account_name": am.get("cash", "Cash in Drawer"),
                "amount": summary["refunds"],
                "memo": "Refunds from Toast",
            })

        # === CREDIT LINES – DOANH THU ===

        # Chiến lược 1: tách theo category (food / bar / …)
        # Chiến lược 2: tách theo source  (doordash / uber / in_store / …)
        # Ưu tiên: nếu có source_account_map → dùng source; else dùng category; else gộp.

        revenue_credited = Decimal("0")

        if src_map and summary.get("sales_by_source"):
            # --- Tách theo kênh bán ---
            for src_key, amount in summary["sales_by_source"].items():
                if amount <= 0:
                    continue
                acct = src_map.get(src_key, am.get("sales_revenue", "Food Sales"))
                lines.append({
                    "type": "credit",
                    "account_name": acct,
                    "amount": amount,
                    "memo": f"Sales - {src_key}",
                })
                revenue_credited += amount

        elif cat_map and summary.get("sales_by_category"):
            # --- Tách theo category ---
            for cat_key, amount in summary["sales_by_category"].items():
                if amount <= 0:
                    continue
                acct = cat_map.get(cat_key, am.get("sales_revenue", "Food Sales"))
                lines.append({
                    "type": "credit",
                    "account_name": acct,
                    "amount": amount,
                    "memo": f"Sales - {cat_key}",
                })
                revenue_credited += amount

        # Fallback: nếu chưa credit đủ (hoặc chưa có map) → gộp
        remainder = summary["gross_sales"] - revenue_credited
        if remainder > 0:
            lines.append({
                "type": "credit",
                "account_name": am.get("sales_revenue", "Food Sales"),
                "amount": remainder,
                "memo": "Gross sales from Toast",
            })

        # === CREDIT LINES – PHỤ ===

        if summary["tax"] > 0:
            lines.append({
                "type": "credit",
                "account_name": am.get("sales_tax_payable", "Sales Tax Payable"),
                "amount": summary["tax"],
                "memo": "Sales tax from Toast",
            })

        if summary["tips"] > 0:
            lines.append({
                "type": "credit",
                "account_name": am.get("tips_payable", "Tips Payable"),
                "amount": summary["tips"],
                "memo": "Tips from Toast",
            })

        if summary["service_charges"] > 0:
            lines.append({
                "type": "credit",
                "account_name": am.get("service_charge_income", "Service Charge Income"),
                "amount": summary["service_charges"],
                "memo": "Service charges from Toast",
            })

        lines = [l for l in lines if l["amount"] > 0]
        return lines

    def _log_summary(self, date: str, summary: dict):
        """In báo cáo tóm tắt"""
        logger.info(f"\n{'─'*50}")
        logger.info(f"📊 BÁO CÁO DOANH THU NGÀY {date}")
        logger.info(f"{'─'*50}")
        logger.info(f"  Số đơn hàng:          {summary['order_count']}")
        logger.info(f"  Doanh thu gộp:        ${summary['gross_sales']:>12}")
        logger.info(f"  Giảm giá:             ${summary['discounts']:>12}")
        logger.info(f"  Doanh thu thuần:      ${summary['net_sales']:>12}")
        logger.info(f"  Thuế:                 ${summary['tax']:>12}")
        logger.info(f"  Tips:                 ${summary['tips']:>12}")
        logger.info(f"  Phí dịch vụ:          ${summary['service_charges']:>12}")

        if summary.get("sales_by_category"):
            logger.info(f"  ───── Doanh thu theo loại ─────")
            for cat, amt in sorted(summary["sales_by_category"].items()):
                logger.info(f"    {cat:<22} ${amt:>12}")

        if summary.get("sales_by_source"):
            logger.info(f"  ───── Doanh thu theo kênh ─────")
            for src, amt in sorted(summary["sales_by_source"].items()):
                logger.info(f"    {src:<22} ${amt:>12}")

        if summary.get("by_revenue_center"):
            logger.info(f"  ───── Theo Revenue Center ─────")
            for rc, amt in sorted(summary["by_revenue_center"].items()):
                logger.info(f"    {rc:<22} ${amt:>12}")

        logger.info(f"  ───── Thanh toán ─────")
        logger.info(f"  Tiền mặt:             ${summary['cash_payments']:>12}")
        logger.info(f"  Thẻ tín dụng:         ${summary['credit_card_payments']:>12}")
        logger.info(f"  Gift card:            ${summary['gift_card_payments']:>12}")
        logger.info(f"  Khác:                 ${summary['other_payments']:>12}")
        logger.info(f"  Hoàn tiền:            ${summary['refunds']:>12}")
        logger.info(f"{'─'*50}\n")

    def sync_yesterday(self):
        """Đồng bộ doanh thu ngày hôm qua"""
        yesterday = datetime.now() - timedelta(days=1)
        return self.sync_date(yesterday)

    def sync_date_range(self, start_date: datetime, end_date: datetime):
        """Đồng bộ nhiều ngày"""
        current = start_date
        results = []
        while current <= end_date:
            result = self.sync_date(current)
            results.append({"date": current.strftime("%Y-%m-%d"), **result})
            current += timedelta(days=1)
            time.sleep(1)  # Tránh rate limit
        return results

    def list_qb_accounts(self):
        """Liệt kê tất cả tài khoản trong QuickBooks (dùng để cấu hình mapping)"""
        try:
            self.qb.connect()
            accounts = self.qb.query_accounts()
            
            logger.info(f"\n{'='*70}")
            logger.info(f"📋 DANH SÁCH TÀI KHOẢN QUICKBOOKS ({len(accounts)} tài khoản)")
            logger.info(f"{'='*70}")
            logger.info(f"{'Tên tài khoản':<40} {'Loại':<25} {'Số':<10}")
            logger.info(f"{'─'*40} {'─'*25} {'─'*10}")
            
            for acct in accounts:
                if acct["is_active"] == "true":
                    logger.info(
                        f"{acct['full_name']:<40} "
                        f"{acct['account_type']:<25} "
                        f"{acct['account_number']:<10}"
                    )
            return accounts
        finally:
            self.qb.disconnect()


# =============================================================================
# PHẦN 4: CHƯƠNG TRÌNH CHÍNH
# =============================================================================

def run_scheduled_sync(config: dict):
    """Chạy đồng bộ tự động theo lịch"""
    sync_time = config.get("schedule", {}).get("sync_time", "06:00")
    
    engine = ToastQBSyncEngine(config)
    
    schedule.every().day.at(sync_time).do(engine.sync_yesterday)
    
    logger.info(f"🕐 Đã lên lịch đồng bộ tự động lúc {sync_time} mỗi ngày")
    logger.info("Nhấn Ctrl+C để dừng\n")
    
    while True:
        schedule.run_pending()
        time.sleep(60)


def main():
    """Điểm bắt đầu chương trình"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Toast POS → QuickBooks Desktop Enterprise Sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  python toast_to_quickbooks.py --list-accounts     Xem danh sách tài khoản QB
  python toast_to_quickbooks.py --sync-yesterday     Đồng bộ doanh thu hôm qua
  python toast_to_quickbooks.py --sync-date 2026-02-25
  python toast_to_quickbooks.py --sync-range 2026-02-01 2026-02-25
  python toast_to_quickbooks.py --auto               Chạy tự động theo lịch
        """,
    )
    parser.add_argument("--list-accounts", action="store_true", help="Liệt kê tài khoản QuickBooks")
    parser.add_argument("--sync-yesterday", action="store_true", help="Đồng bộ ngày hôm qua")
    parser.add_argument("--sync-date", type=str, help="Đồng bộ ngày cụ thể (YYYY-MM-DD)")
    parser.add_argument("--sync-range", nargs=2, type=str, help="Đồng bộ khoảng ngày (start end)")
    parser.add_argument("--auto", action="store_true", help="Chạy tự động theo lịch")
    parser.add_argument("--test-toast", action="store_true", help="Test kết nối Toast API")
    parser.add_argument("--test-qb", action="store_true", help="Test kết nối QuickBooks")

    args = parser.parse_args()
    config = load_config()

    if args.test_toast:
        logger.info("🧪 Test kết nối Toast API...")
        client = ToastAPIClient(config)
        try:
            client.authenticate()
            logger.info("✅ Kết nối Toast API thành công!")
        except Exception as e:
            logger.error(f"❌ Lỗi: {e}")

    elif args.test_qb:
        logger.info("🧪 Test kết nối QuickBooks Desktop...")
        client = QuickBooksDesktopClient(config)
        try:
            client.connect()
            logger.info("✅ Kết nối QuickBooks Desktop thành công!")
        except Exception as e:
            logger.error(f"❌ Lỗi: {e}")
        finally:
            client.disconnect()

    elif args.list_accounts:
        engine = ToastQBSyncEngine(config)
        engine.list_qb_accounts()

    elif args.sync_yesterday:
        engine = ToastQBSyncEngine(config)
        result = engine.sync_yesterday()
        if result.get("success"):
            logger.info("🎉 Đồng bộ hoàn tất!")
        else:
            logger.error(f"Đồng bộ thất bại: {result.get('message')}")

    elif args.sync_date:
        date = datetime.strptime(args.sync_date, "%Y-%m-%d")
        engine = ToastQBSyncEngine(config)
        result = engine.sync_date(date)
        if result.get("success"):
            logger.info("🎉 Đồng bộ hoàn tất!")

    elif args.sync_range:
        start = datetime.strptime(args.sync_range[0], "%Y-%m-%d")
        end = datetime.strptime(args.sync_range[1], "%Y-%m-%d")
        engine = ToastQBSyncEngine(config)
        results = engine.sync_date_range(start, end)
        success = sum(1 for r in results if r.get("success"))
        logger.info(f"🎉 Hoàn tất: {success}/{len(results)} ngày thành công")

    elif args.auto:
        run_scheduled_sync(config)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
