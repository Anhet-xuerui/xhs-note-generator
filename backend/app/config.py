"""运行配置：两组独立 provider + 价格表。

设计约束（见设计文档 §13、§4）：

- **读者必须走独立 provider**。`READER_*` 缺失时 `Settings.load()` 直接报错，不提供
  「回落到 WRITER_*」的路径——两个 temperature 不是换厂商，E2 会因此作废。
- 价格表单位是「美元 / 百万 token」，取**高峰价**（保守上界），避免成本被低估。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# 价格抓取日期 2026-10-24，来源：https://api-docs.deepseek.com/quick_start/pricing
# 单位：美元 / 百万 token，(输入价, 输出价)；取高峰价（见 PAGE 的 PEAK 行）。
# 换模型或厂商调价时改这里，并在注释里更新日期与出处。
PRICES: dict[str, tuple[float, float]] = {
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
}


class ProviderNotConfigured(RuntimeError):
    """provider 配置缺失。"""


class ReaderNotConfigured(ProviderNotConfigured):
    """读者执行者未配置。"""


class WriterNotConfigured(ProviderNotConfigured):
    """主笔执行者未配置。"""


class UnknownModelPrice(RuntimeError):
    """价格表里没有这个模型——宁可报错，也不要按 0 计费把成本数字变成假的。"""

    def __init__(self, model: str) -> None:
        super().__init__(f"模型 {model} 未登记价格：请加进 app/config.py 的 PRICES（含抓取日期）。")
        self.model = model


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    writer_base_url: str = "https://api.deepseek.com"
    writer_model: str = "deepseek-flash"
    writer_api_key: str | None = None

    reader_base_url: str | None = None
    reader_model: str | None = None
    reader_api_key: str | None = None

    request_timeout_s: float = 60.0
    max_retries: int = 1

    # 价格表以美元计价（厂商原价），折人民币用这个汇率；改汇率请同时更新注释日期。
    usd_cny_rate: float = 7.1
    # DeepSeek 默认开启思考模式（会忽略 temperature 并推高时延）；本项目默认关闭。
    thinking_enabled: bool = False

    @classmethod
    def load(cls) -> Settings:
        """读取环境变量并校验。

        读者先校验：它是「换厂商」机制的开关，缺了必须立刻失败。
        """
        settings = cls()
        missing_reader = [
            name
            for name, value in (
                ("READER_BASE_URL", settings.reader_base_url),
                ("READER_MODEL", settings.reader_model),
                ("READER_API_KEY", settings.reader_api_key),
            )
            if not value
        ]
        if missing_reader:
            raise ReaderNotConfigured(
                "缺少 READER_ 配置："
                + ", ".join(missing_reader)
                + "。读者必须使用另一家厂商的模型（§13：换厂商是机制，不是偏好），"
                "不会回落到 WRITER_*；请照 .env.example 填好读者那一组。"
            )

        if not settings.writer_api_key:
            raise WriterNotConfigured("缺少 WRITER_API_KEY，主笔无法调用模型。")

        # 价格必须先登记：否则会在花掉画像官/策划/主笔的钱之后才炸（评审 C2）。
        if settings.reader_model not in PRICES:
            raise UnknownModelPrice(settings.reader_model or "")

        # 「换厂商」是机制不是偏好（§13）：同一家同一模型等于没换，E2 会作废。
        same_vendor = (settings.reader_base_url, settings.reader_model) == (
            settings.writer_base_url,
            settings.writer_model,
        )
        if same_vendor:
            raise ReaderNotConfigured(
                "读者配置与主笔完全相同（同 base_url 同模型），等于没有换厂商；"
                "§13 要求读者用另一家厂商的模型，请改 READER_BASE_URL / READER_MODEL。"
            )
        return settings
