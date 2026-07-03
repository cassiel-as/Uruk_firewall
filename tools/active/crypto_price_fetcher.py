# 加密貨幣價格查詢工具
import httpx

TOOL_NAME = "crypto_price_fetcher"
TOOL_METHOD = "tool_run"
TOOL_PARAMS_SCHEMA = {} # 無需參數，幣種固定

def tool_run(params: dict) -> dict:
    """
    獲取比特幣 (BTC)、以太坊 (ETH) 和 Solana (SOL) 的美元價格。
    """
    api_url = "https://api.coingecko.com/api/v3/simple/price"
    coin_ids = "bitcoin,ethereum,solana"
    vs_currency = "usd"

    try:
        response = httpx.get(
            api_url,
            params={"ids": coin_ids, "vs_currencies": vs_currency},
            timeout=10
        )
        response.raise_for_status() # Raises HTTPStatusError for bad responses (4xx or 5xx)
        data = response.json()

        btc_price = data.get("bitcoin", {}).get("usd")
        eth_price = data.get("ethereum", {}).get("usd")
        sol_price = data.get("solana", {}).get("usd")

        if btc_price is None or eth_price is None or sol_price is None:
            return {"status": "error", "message": "未能獲取所有指定加密貨幣的價格。API響應可能不完整。"}

        return {
            "status": "ok",
            "data": {
                "bitcoin": {"usd": btc_price},
                "ethereum": {"usd": eth_price},
                "solana": {"usd": sol_price},
            }
        }

    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": f"CoinGecko API 返回錯誤狀態碼: {e.response.status_code} - {e.response.text}"}
    except httpx.RequestError as e:
        return {"status": "error", "message": f"請求 CoinGecko API 時發生網絡錯誤: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"處理 CoinGecko API 響應時發生未知錯誤: {e}"}