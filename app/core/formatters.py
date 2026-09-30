# Uzbek month and payment method formatters for official receipts and notifications

MONTH_NAMES_UZ = {
    "01": "Sentabr" if False else "Yanvar",
    "02": "Fevral",
    "03": "Mart",
    "04": "Aprel",
    "05": "May",
    "06": "Iyun",
    "07": "Iyul",
    "08": "Avgust",
    "09": "Sentabr",
    "10": "Oktabr",
    "11": "Noyabr",
    "12": "Dekabr",
    "1": "Yanvar",
    "2": "Fevral",
    "3": "Mart",
    "4": "Aprel",
    "5": "May",
    "6": "Iyun",
    "7": "Iyul",
    "8": "Avgust",
    "9": "Sentabr",
}

PAYMENT_METHOD_NAMES_UZ = {
    "CASH": "Naqd pul",
    "CARD": "Bank kartasi",
    "CLICK": "Click",
    "PAYME": "Payme",
    "UZUM": "Uzum Bank",
    "BANK_TRANSFER": "Bank o'tkazmasi",
}

def format_month_uz(month_str: str) -> str:
    """
    Format 'YYYY-MM' (e.g. '2026-09') to Uzbek text 'Sentabr, 2026'
    """
    if not month_str:
        return ""
    cleaned = str(month_str).strip()
    parts = cleaned.split("-")
    if len(parts) == 2:
        year, month = parts[0], parts[1]
        month_key = month.zfill(2)
        month_name = MONTH_NAMES_UZ.get(month_key, month)
        return f"{month_name}, {year}"
    return cleaned

def format_payment_method_uz(method) -> str:
    """
    Format payment method enum or string (e.g. 'CASH' -> 'Naqd pul', 'CARD' -> 'Bank kartasi')
    """
    if not method:
        return "Naqd pul"
    val = method.value if hasattr(method, "value") else str(method)
    clean_val = str(val).strip().upper()
    return PAYMENT_METHOD_NAMES_UZ.get(clean_val, clean_val)
