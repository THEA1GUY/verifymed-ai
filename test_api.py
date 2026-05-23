import httpx
import asyncio
import json

async def test_verify():
    payload = {
        "brand_name": "Lonart",
        "manufacturer": "Greenlife Pharmaceuticals",
        "batch_number": "LNR-2025-01",
        "active_ingredients": ["Artemether", "Lumefantrine"],
        "stated_therapeutic_use": "Treatment of uncomplicated malaria"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post("http://localhost:8000/verify", json=payload, timeout=30.0)
        print(json.dumps(response.json(), indent=2))

if __name__ == "__main__":
    asyncio.run(test_verify())
