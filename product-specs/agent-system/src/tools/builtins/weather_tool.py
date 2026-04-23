"""天气查询工具 — 内置工具，供 travel-planner 等子 Agent 使用

使用 wttr.in 免费 API 获取真实天气数据，无需 API key。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WeatherInput(BaseModel):
    city: str = Field(description="城市名称（中文或英文），如 '北京'、'Shanghai'")
    days: int = Field(default=3, description="预报天数（1-3）")


class WeatherTool(BaseTool):
    """查询城市天气预报"""

    name: str = "get_weather"
    description: str = "查询指定城市的天气预报。传入城市名称和预报天数。"
    args_schema: type[BaseModel] = WeatherInput

    def _run(self, city: str, days: int = 3) -> str:
        import urllib.request
        import json

        days = min(max(days, 1), 3)
        url = f"https://wttr.in/{city}?format=j1"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DeepAgent/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("天气查询失败: city=%s, error=%s", city, e)
            return f"天气查询失败: {e}"

        # 解析当前天气
        current = data.get("current_condition", [{}])[0]
        temp = current.get("temp_C", "?")
        feels = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        desc_cn = current.get("lang_zh", [{}])
        desc = desc_cn[0].get("value", current.get("weatherDesc", [{}])[0].get("value", "")) if desc_cn else ""

        lines = [
            f"## {city} 天气预报",
            f"**当前**: {desc}, {temp}°C (体感 {feels}°C), 湿度 {humidity}%",
            "",
        ]

        # 解析未来天数
        forecasts = data.get("weather", [])[:days]
        for fc in forecasts:
            date = fc.get("date", "")
            max_t = fc.get("maxtempC", "?")
            min_t = fc.get("mintempC", "?")
            hourly = fc.get("hourly", [])
            # 取中午的天气描述
            noon = hourly[4] if len(hourly) > 4 else hourly[0] if hourly else {}
            noon_desc_cn = noon.get("lang_zh", [{}])
            noon_desc = noon_desc_cn[0].get("value", "") if noon_desc_cn else noon.get("weatherDesc", [{}])[0].get("value", "")
            rain = noon.get("chanceofrain", "0")
            lines.append(f"**{date}**: {noon_desc}, {min_t}~{max_t}°C, 降雨概率 {rain}%")

        return "\n".join(lines)

    async def _arun(self, city: str, days: int = 3) -> str:
        return self._run(city=city, days=days)
