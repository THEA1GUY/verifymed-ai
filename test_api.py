import httpx
import asyncio
import json
import time

async def run_test(name, payload):
    print(f"\n[RUNNING TEST]: {name}")
    async with httpx.AsyncClient() as client:
        start_time = time.monotonic()
        try:
            response = await client.post("http://localhost:8000/verify", json=payload, timeout=90.0)
            duration = (time.monotonic() - start_time) * 1000
            print(f"[TIME]: {duration:.1f}ms")
            
            if response.status_code != 200:
                print(f"[FAIL] status code: {response.status_code}")
                print(response.text)
                return
                
            res = response.json()
            print(f"[SUCCESS] Status: {res.get('status')}")
            print(f"Tier: {res.get('tier')}")
            verdict = res.get('verdict', {})
            print(f"Risk Level: {verdict.get('risk_level')}")
            print(f"Confidence: {verdict.get('confidence_score_percentage')}%")
            print(f"Suspicion Score: {verdict.get('suspicion_score')}")
            print(f"Flags: {res.get('agent_outputs', {}).get('agent_preflight', {}).get('flags')}")
            
        except Exception as e:
            print(f"[ERROR] Request failed: {e}")

async def main():
    # Test Case 1: Tier 1 - Hard Fail (GTIN Manufacturer Mismatch)
    # Printed manufacturer is "Greenlife Pharmaceuticals" but GTIN resolves to something else (or we flag a batch mismatch)
    payload_hard_fail = {
        "patient_symptoms": "High fever and headache",
        "drugs": [
            {
                "brand_name": "Lonart",
                "manufacturer": "Greenlife Pharmaceuticals",
                "batch_number": "LNR-2025-01",
                "active_ingredients": ["Artemether", "Lumefantrine"],
                "stated_therapeutic_use": "Treatment of uncomplicated malaria",
                "nafdac_number": "A4-100137"
            }
        ],
        "preflight": {
            "barcode_raw": "010890111122223410LNR-2025-0217260531", # Mismatched batch number: LNR-2025-02 vs LNR-2025-01
            "barcode_gtin": "08901111222234",
            "barcode_batch": "LNR-2025-02",
            "barcode_expiry": "260531",
            "printed_batch": "LNR-2025-01",
            "printed_expiry": "26-05-2026",
            "printed_manufacturer": "Greenlife Pharmaceuticals"
        }
    }
    await run_test("Tier 1 - Hard Fail (Batch number mismatch)", payload_hard_fail)

    # Test Case 2: Tier 2 - Soft Flag (Invalid NAFDAC format)
    # NAFDAC format is malformed (e.g. A7-1234 instead of A4-XXXX)
    payload_soft_flag = {
        "patient_symptoms": "Joint pains and fever",
        "drugs": [
            {
                "brand_name": "Coartem",
                "manufacturer": "Novartis",
                "batch_number": "CO-9988",
                "active_ingredients": ["Artemether", "Lumefantrine"],
                "stated_therapeutic_use": "Treatment of malaria",
                "nafdac_number": "A7-1234" # Invalid prefix format
            }
        ],
        "preflight": {
            "barcode_raw": "010761315500123410CO-998817280930",
            "barcode_gtin": "07613155001234",
            "barcode_batch": "CO-9988",
            "barcode_expiry": "280930",
            "printed_batch": "CO-9988",
            "printed_expiry": "30-09-2028",
            "printed_manufacturer": "Novartis"
        }
    }
    await run_test("Tier 2 - Soft Flag (Invalid NAFDAC format)", payload_soft_flag)

    # Test Case 3: Tier 3 - Clean (Well-formed request)
    payload_clean = {
        "patient_symptoms": "Severe fever and body aches",
        "drugs": [
            {
                "brand_name": "Lonart",
                "manufacturer": "Greenlife Pharmaceuticals",
                "batch_number": "LNR-2025-01",
                "active_ingredients": ["Artemether", "Lumefantrine"],
                "stated_therapeutic_use": "Treatment of uncomplicated malaria",
                "nafdac_number": "A4-100137" # Valid imported NAFDAC format
            }
        ],
        "preflight": {
            "barcode_raw": "010890111122223410LNR-2025-0117280531",
            "barcode_gtin": "08901111222234",
            "barcode_batch": "LNR-2025-01",
            "barcode_expiry": "280531",
            "printed_batch": "LNR-2025-01",
            "printed_expiry": "31-05-2028",
            "printed_manufacturer": "Greenlife Pharmaceuticals"
        }
    }
    await run_test("Tier 3 - Clean Verification", payload_clean)

if __name__ == "__main__":
    asyncio.run(main())
