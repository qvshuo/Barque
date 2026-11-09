"""Fixed seven-subscription dataset shared by browser checks."""


def configuration():
    return {
        "version": 1,
        "settings": {
            "timezone": "Asia/Shanghai",
            "check_interval_seconds": 3600,
            "remind_before_days": 7,
            "notify_url": "",
            "reminder_time": "09:00",
        },
        "categories": [f"分类{i + 1}" for i in range(7)],
        "subscriptions": [
            {
                "id": f"{i + 1:032x}",
                "name": f"订阅{i + 1}",
                "category": f"分类{i + 1}",
                "billing_cycle": "month",
                "payment_date": "2024-01-31",
                "amount": 70 - i * 10,
                "currency": "CNY",
                "notify_enabled": True,
            }
            for i in range(7)
        ],
    }
