"""运行配置：两组独立 provider + 价格表。

设计约束（见设计文档 §13、§4、D11）：

- **读者的 provider 仍然独立配置**：`READER_*` 缺失时 `Settings.load()` 直接报错，不提供
  「回落到 WRITER_*」的路径。D11 起**模型**可以自由选、也允许和主笔相同——但那样的 run
  会被标记为「非独立评审」，E2/E3 的结论不适用于它。
- 价格表单位是「美元 / 百万 token」，取**高峰价**（保守上界）。表里没有的模型也能跑：
  token 照记，成本记成「未计价」，绝不写 0（成本不许估算）。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# 价格抓取日期 2026-10-24，来源：https://api-docs.deepseek.com/quick_start/pricing
# 单位：美元 / 百万 token，(输入价, 输出价)；取高峰价（见 PAGE 的 PEAK 行）。
# 换模型或厂商调价时改这里，并在注释里更新日期与出处。
PRICES: dict[str, tuple[float, float]] = {
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4.1-flash": (0.30, 1.20),   # 与 deepseek-flash 同一模型的不同别名（官方定价页）
    "deepseek-v4-pro": (1.32, 3.96),
    # 未核实：智谱 GLM flash 档的保守上界，只影响成本显示与预算判断，不影响 token 统计。
    # 核实后请按官方定价页改正，并更新这一行的日期。
    "glm-5.3-flash": (0.50, 0.50),
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
    def load(cls, *, _env_file: str | None = ".env") -> Settings:
        """读取环境变量并校验。

        读者先校验：它是「换厂商」机制的开关，缺了必须立刻失败。
        """
        # 测试传 None，避免读到开发者本机的 .env。pydantic-settings 运行时支持该参数，
        # 但类型存根里没有，所以这里显式忽略。
        settings = cls(_env_file=_env_file)  # type: ignore[call-arg]
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

        # D11 起：模型可以自由选（含未登记价格的），也可以与读者相同。
        # 「成本不许估算」改由 Usage.unpriced_calls 承担：没价格就报「未计价」，不写 0。
        return settings
