import httpx
import asyncio
import json

payload = {
    "patient_symptoms": "High fever, chills, sweating, and body aches for 3 days. Suspected malaria.",
    "drugs": [
        {
            "brand_name": "Coartem",
            "manufacturer": "Novartis Pharma AG",
            "batch_number": "T0552A",
            "active_ingredients": ["Artemether 20mg", "Lumefantrine 120mg"],
            "stated_therapeutic_use": "Treatment of acute uncomplicated Plasmodium falciparum malaria",
            "nafdac_number": "A4-0392"
        }
    ],
    "preflight": {
        "barcode_gtin": "07613326016551",
        "barcode_batch": "T0552A",
        "barcode_expiry": "271130",
        "printed_batch": "T0552A",
        "printed_expiry": "30-11-2027",
        "printed_manufacturer": "Novartis Pharma AG"
    }
}

async def run():
    print("=" * 55)
    print("  LIVE DRUG TEST: Coartem 24-tab by Novartis Pharma AG")
    print("  NAFDAC: A4-0392 | Batch: T0552A | Exp: Nov 2027")
    print("=" * 55)

    async with httpx.AsyncClient() as client:
        r = await client.post("http://localhost:8000/verify", json=payload, timeout=90.0)
        data = r.json()

    v = data["verdict"]
    pf = data["agent_outputs"]["agent_preflight"]
    a1 = data["agent_outputs"]["agent_1_identity"]
    a2 = data["agent_outputs"]["agent_2_intelligence"]
    a3 = data["agent_outputs"]["agent_3_science"]

    print(f"\nTIER:             {data['tier']}")
    print(f"PREFLIGHT FLAGS:  {pf['flags'] or 'None'}")
    print(f"SUSPICION SCORE:  {v['suspicion_score']}")
    print(f"RISK LEVEL:       {v['risk_level']}")
    print(f"CONFIDENCE:       {v['confidence_score_percentage']}%")

    print("\n--- AGENT 1 — Registry & Identity ---")
    for a in a1:
        print(f"  Registered:      {a.get('manufacturer_registered')}")
        print(f"  Registry Match:  {a.get('registry_match_found')}")
        print(f"  Suspicion:       {a.get('suspicion_agent1')}")
        print(f"  Anomalies:       {a.get('flagged_anomalies')}")

    print("\n--- AGENT 2 — Global Intelligence ---")
    for a in a2:
        print(f"  Counterfeit Alerts: {a.get('counterfeit_alerts_found')}")
        print(f"  Recall Notices:     {a.get('recall_notices_found')}")
        print(f"  Suspicion:          {a.get('suspicion_agent2')}")
        print(f"  Details:            {a.get('details')}")

    print("\n--- AGENT 3 — Science (PubChem/ChEMBL) ---")
    for a in a3:
        print(f"  Pharmacologically Consistent: {a.get('pharmacologically_consistent')}")
        print(f"  Inconsistencies:              {a.get('inconsistencies_found')}")
        print(f"  Suspicion:                    {a.get('suspicion_agent3')}")
        print(f"  Analysis:                     {a.get('analysis')}")

    print("\n--- AGENT 5 — FINAL VERDICT ---")
    print(f"\nINVESTIGATOR CONCERNS:\n{v['investigators_concerns']}")
    print(f"\nPATIENT SUMMARY:\n{v['patient_summary']}")
    print(f"\nACTIONABLE STEPS:")
    for step in v["actionable_steps"]:
        print(f"  * {step}")
    print(f"\nSIDE EFFECTS & INTERACTIONS:\n{v['side_effects_and_interactions']}")
    print(f"\nWHAT TO CHECK ON PACK:\n{v['what_to_check_on_pack']}")
    print(f"\nWHO TO CONTACT:\n{v['who_to_contact']}")
    print("\n" + "=" * 55)

asyncio.run(run())
