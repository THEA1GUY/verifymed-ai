import os
import json
import httpx
import asyncio
import re
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Literal
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="VerifyMed Real-Time Authentication")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
app.mount("/static", StaticFiles(directory="."), name="static")

# Ensure API Key exists
groq_key = os.getenv("GROQ_API_KEY")
if not groq_key:
    print("WARNING: GROQ_API_KEY not found in .env")

groq_client = AsyncGroq(api_key=groq_key)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

STAGE_0_MODEL = "llama-3.2-90b-vision-preview"
AGENT_1_MODEL = "llama-3.1-8b-instant"
AGENT_2_MODEL = "llama-3.1-8b-instant" # Downgraded to 8b for fast summarisation
AGENT_3_MODEL = "llama-3.3-70b-versatile"
AGENT_4_MODEL = "llama-3.3-70b-versatile"
AGENT_5_MODEL = "llama-3.3-70b-versatile"
CHAT_MODEL = "llama-3.1-8b-instant"

class DrugInfo(BaseModel):
    brand_name: str
    manufacturer: str
    batch_number: str
    active_ingredients: List[str]
    stated_therapeutic_use: str
    nafdac_number: Optional[str] = None # Added for NAFDAC validation

class PreflightData(BaseModel):
    barcode_raw: Optional[str] = None
    barcode_gtin: Optional[str] = None
    barcode_batch: Optional[str] = None
    barcode_expiry: Optional[str] = None
    printed_batch: Optional[str] = None
    printed_expiry: Optional[str] = None
    printed_manufacturer: Optional[str] = None

class PreflightResult(BaseModel):
    tier: Literal["hard_fail", "soft_flag", "clean"]
    suspicion_preflight: float
    flags: List[str]
    gs1_resolved_manufacturer: Optional[str] = None

class VerifyRequest(BaseModel):
    patient_symptoms: str
    drugs: List[DrugInfo]
    preflight: Optional[PreflightData] = None # Attached preflight context

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]

# Utility for Tavily Search
async def search_tavily(query: str) -> str:
    if not TAVILY_API_KEY:
        return "Tavily API key missing. Unable to search."
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "basic", "max_results": 3},
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            return "\n".join([res.get("content", "") for res in data.get("results", [])])
        except Exception as e:
            return f"Search failed: {str(e)}"
async def check_who_registry(brand_name: str, manufacturer: str) -> str:
    query = f"site:extranet.who.int/pqweb {brand_name} {manufacturer}"
    return await search_tavily(query)

async def fetch_openfda_ndc(gtin: str) -> str:
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://api.fda.gov/drug/ndc.json?search=product_ndc:\"{gtin}\"&limit=1"
            response = await client.get(url, timeout=5.0)
            if response.status_code == 200:
                results = response.json().get("results", [])
                if results:
                    return results[0].get("labeler_name", "Unknown")
        except Exception:
            pass
    return "Unknown"

async def fuzzy_compare_manufacturers(printed: str, resolved_tavily: str, resolved_fda: str) -> dict:
    prompt = f"""Compare the printed manufacturer name with the resolved manufacturer information from GTIN lookups.
Printed manufacturer: "{printed}"
Tavily Search results: "{resolved_tavily}"
OpenFDA Labeller name: "{resolved_fda}"

Determine if the printed manufacturer matches the resolved manufacturer. Consider common abbreviations, parent companies, or subsidiaries.
If both lookups are completely empty or fail to find any manufacturer, set match to true (insufficient data to fail).
If there is a clear mismatch (e.g. printed is "Pfizer" but resolved is "Local Herbal Co"), set match to false.

Output JSON:
{{
  "match": true/false,
  "confidence_percentage": 0-100,
  "reason": "Brief explanation"
}}"""
    try:
        res = await groq_client.chat.completions.create(
            model=AGENT_1_MODEL,
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=5.0
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"Fuzzy comparison failed: {e}")
        return {"match": True, "confidence_percentage": 100, "reason": f"Fuzzy comparison check skipped due to error: {e}"}

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%y%m%d", "%Y-%m-%d", "%m/%y", "%m/%Y", "%Y-%m", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

async def run_preflight(preflight: Optional[PreflightData], drugs: List[DrugInfo]) -> PreflightResult:
    flags = []
    suspicion = 0.0
    resolved_mfg = None
    
    # 1. NAFDAC format check
    for drug in drugs:
        if drug.nafdac_number:
            nafdac_clean = drug.nafdac_number.strip()
            if not re.match(r"^(A4|B4|04|C4)-\d{4,6}$", nafdac_clean):
                flags.append(f"Invalid NAFDAC number format on {drug.brand_name}: '{drug.nafdac_number}'")
                suspicion += 0.3
                
    if not preflight:
        tier = "soft_flag" if suspicion >= 0.3 else "clean"
        return PreflightResult(
            tier=tier,
            suspicion_preflight=min(suspicion, 1.0),
            flags=flags,
            gs1_resolved_manufacturer=None
        )
        
    # 2. GTIN resolution
    if preflight.barcode_gtin:
        gtin = preflight.barcode_gtin.strip()
        printed_mfg = preflight.printed_manufacturer or (drugs[0].manufacturer if drugs else "")
        
        fda_task = fetch_openfda_ndc(gtin)
        tavily_task = search_tavily(f'"{gtin}" drug manufacturer')
        
        fda_labeller, tavily_mfg = await asyncio.gather(fda_task, tavily_task)
        
        if printed_mfg:
            comp = await fuzzy_compare_manufacturers(printed_mfg, tavily_mfg, fda_labeller)
            resolved_mfg = fda_labeller if fda_labeller != "Unknown" else (tavily_mfg[:100] if tavily_mfg else "Unknown")
            if not comp.get("match", True) and comp.get("confidence_percentage", 100) < 80:
                flags.append(f"GTIN manufacturer mismatch: Printed '{printed_mfg}' vs Resolved '{resolved_mfg}' (Reason: {comp.get('reason')})")
                suspicion = 1.0  # Hard fail
                
    # 3. Batch number check
    if preflight.barcode_batch and preflight.printed_batch:
        if preflight.barcode_batch.strip() != preflight.printed_batch.strip():
            flags.append(f"Batch number mismatch: Barcode '{preflight.barcode_batch}' vs Printed '{preflight.printed_batch}'")
            suspicion = 1.0  # Hard fail
            
    # 4. Expiry date plausibility
    printed_exp_dt = parse_date(preflight.printed_expiry)
    if printed_exp_dt:
        now = datetime.now()
        if printed_exp_dt < now:
            flags.append(f"Printed expiry date is in the past: {preflight.printed_expiry}")
            suspicion += 0.5
        elif (printed_exp_dt - now).days > 5 * 365:
            flags.append(f"Printed expiry date is suspiciously far in the future (>5 years): {preflight.printed_expiry}")
            suspicion += 0.3
            
    barcode_exp_dt = parse_date(preflight.barcode_expiry)
    if barcode_exp_dt:
        now = datetime.now()
        if barcode_exp_dt < now:
            flags.append(f"Barcode expiry date is in the past: {preflight.barcode_expiry}")
            suspicion += 0.5
            
    if printed_exp_dt and barcode_exp_dt:
        if printed_exp_dt.year != barcode_exp_dt.year or printed_exp_dt.month != barcode_exp_dt.month:
            flags.append(f"Expiry date mismatch: Barcode '{preflight.barcode_expiry}' vs Printed '{preflight.printed_expiry}'")
            suspicion = 1.0  # Hard fail
            
    if suspicion >= 0.8:
        tier = "hard_fail"
    elif suspicion >= 0.3:
        tier = "soft_flag"
    else:
        tier = "clean"
        
    return PreflightResult(
        tier=tier,
        suspicion_preflight=min(suspicion, 1.0),
        flags=flags,
        gs1_resolved_manufacturer=resolved_mfg
    )

async def run_agent_1_identity(drug: DrugInfo, preflight_flags: List[str]) -> dict:
    queries = [
        f"site:greenbook.nafdac.gov.ng {drug.brand_name} {drug.manufacturer}",
        f"site:extranet.who.int/pqweb {drug.brand_name} {drug.manufacturer}",
        f"site:accessdata.fda.gov {drug.brand_name} {drug.manufacturer}",
        f"site:ema.europa.eu {drug.brand_name} {drug.manufacturer}",
        f"site:cdscoonline.gov.in {drug.brand_name} {drug.manufacturer}",
    ]
    results = await asyncio.gather(*[search_tavily(q) for q in queries])
    
    nafdac_res = results[0]
    who_res = results[1]
    fda_res = results[2]
    ema_res = results[3]
    cdsco_res = results[4]
    
    prompt = f"""You are Agent 1 (Identity). Analyze registry search results for the drug: {drug.brand_name} by {drug.manufacturer}.
Preflight Flags Detected: {preflight_flags}

Registry Search Results:
- NAFDAC (Nigeria): {nafdac_res}
- WHO Prequalification: {who_res}
- US FDA (Orange Book): {fda_res}
- EMA (Europe): {ema_res}
- CDSCO (India): {cdsco_res}

Output JSON:
{{
  "manufacturer_registered": true/false,
  "registry_match_found": true/false,
  "suspicion_agent1": 0.0-1.0,
  "flagged_anomalies": ["list of anomalies or 'None'"]
}}"""
    res = await groq_client.chat.completions.create(
        model=AGENT_1_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

async def run_agent_2_intelligence(drug: DrugInfo, preflight_flags: List[str]) -> dict:
    query = f"{drug.brand_name} {drug.manufacturer} {drug.batch_number} counterfeit OR fake OR recall OR warning"
    news_results = await search_tavily(query)
    
    prompt = f"""You are Agent 2 (Intelligence). Analyze global search results for warnings/recalls/fakes for: {drug.brand_name} (Batch: {drug.batch_number}).
Preflight Flags: {preflight_flags}
Search Results: {news_results}

IMPORTANT SCORING RULES:
- If alerts are found for THIS SPECIFIC BATCH NUMBER ({drug.batch_number}), set suspicion_agent2 to 0.9-1.0.
- If only GENERAL/CATEGORY alerts exist (i.e. this drug TYPE is commonly counterfeited but no specific batch alert), set suspicion_agent2 to 0.4-0.6.
- If no alerts exist at all, set suspicion_agent2 to 0.0-0.2.

Output JSON:
{{
  "counterfeit_alerts_found": true/false,
  "recall_notices_found": true/false,
  "batch_specific_alert": true/false,
  "suspicion_agent2": 0.0-1.0,
  "details": "summary of findings. Explicitly state if the alert is batch-specific or category-wide."
}}"""
    res = await groq_client.chat.completions.create(
        model=AGENT_2_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

async def fetch_pubchem_ingredient(ingredient: str) -> dict:
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{ingredient}/property/MolecularFormula,MolecularWeight,IUPACName/JSON"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                props = data.get("PropertyTable", {}).get("Properties", [])
                if props:
                    return {
                        "cid": props[0].get("CID"),
                        "formula": props[0].get("MolecularFormula"),
                        "weight": props[0].get("MolecularWeight"),
                        "iupac_name": props[0].get("IUPACName")
                    }
        except Exception as e:
            print(f"PubChem lookup for {ingredient} failed: {e}")
    return {"error": "Not found or request failed"}

async def fetch_chembl_ingredient(ingredient: str) -> dict:
    url = f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?pref_name__iexact={ingredient}&limit=1"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                mols = data.get("molecules", [])
                if mols:
                    mol = mols[0]
                    return {
                        "chembl_id": mol.get("molecule_chembl_id"),
                        "type": mol.get("molecule_type"),
                        "max_phase": mol.get("max_phase"),
                        "indications": mol.get("therapeutic_flag")
                    }
        except Exception as e:
            print(f"ChEMBL lookup for {ingredient} failed: {e}")
    return {"error": "Not found or request failed"}

def strip_dosage(ingredient: str) -> str:
    """Strip dosage suffixes like '20mg', '500 mg', '10mcg' from ingredient names
    so PubChem/ChEMBL can find the bare compound name."""
    return re.sub(r'\s*\d+\.?\d*\s*(mg|mcg|g|iu|ml|%|mmol).*', '', ingredient, flags=re.IGNORECASE).strip()

async def fetch_ingredient_data(ingredient: str) -> dict:
    clean_name = strip_dosage(ingredient)
    pub_task = fetch_pubchem_ingredient(clean_name)
    chem_task = fetch_chembl_ingredient(clean_name)
    pub_res, chem_res = await asyncio.gather(pub_task, chem_task)
    return {
        "ingredient": ingredient,
        "clean_name_searched": clean_name,
        "pubchem": pub_res,
        "chembl": chem_res
    }

async def run_agent_3_science(drug: DrugInfo) -> dict:
    ingredients = drug.active_ingredients
    db_tasks = [fetch_ingredient_data(ing) for ing in ingredients]
    db_data = await asyncio.gather(*db_tasks)
    
    prompt = f"""You are Agent 3 (Science). You are an expert pharmacologist and counterfeit detector.
Examine the active ingredients and cross-reference them with the drug's stated therapeutic use, typical brand formulation, and standard scientific database info.

Active Ingredients: {", ".join(ingredients)}
Intended Use: {drug.stated_therapeutic_use}
Brand Name: {drug.brand_name}
Manufacturer: {drug.manufacturer}

Database Validation Data (from PubChem and ChEMBL):
{json.dumps(db_data, indent=2)}

CRITICAL COUNTERFEIT CHECK RULES (read carefully):
1. If the database returns a technical 'error' due to an API/network failure, this is NOT evidence the ingredient is fake. Do NOT raise suspicion based on API errors alone.
2. Only raise HIGH suspicion if the ingredient name is clearly nonsense (e.g. 'chalk', 'water', 'sugar'), OR if PubChem explicitly returns a result confirming it is NOT a pharmaceutical compound.
3. If PubChem or ChEMBL returns valid data for the ingredient, use that to verify consistency with the stated therapeutic use.
4. If ALL database lookups fail (all show errors), note this but set suspicion_agent3 no higher than 0.3 — insufficient data is not proof of a fake.

Also assess if the stated active ingredients are consistent with standard dosages for treating the stated therapeutic use.

Output JSON:
{{
  "pharmacologically_consistent": true/false,
  "inconsistencies_found": ["list"],
  "suspicion_agent3": 0.0-1.0,
  "analysis": "Brief reasoning. If nonsense or heavily mismatched, explicitly state it is likely a fake/counterfeit."
}}"""
    res = await groq_client.chat.completions.create(
        model=AGENT_3_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

async def fetch_openfda(ingredient: str) -> dict:
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://api.fda.gov/drug/label.json?search=active_ingredient:\"{ingredient}\"&limit=1"
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()["results"][0]
                return {
                    "adverse_reactions": data.get("adverse_reactions", ["None listed"])[0][:500],
                    "drug_interactions": data.get("drug_interactions", ["None listed"])[0][:500],
                    "warnings": data.get("warnings", ["None listed"])[0][:500]
                }
        except Exception:
            pass
    return {"adverse_reactions": "Unknown", "drug_interactions": "Unknown", "warnings": "Unknown"}

async def run_agent_4_pharmacovigilance(drugs: List[DrugInfo]) -> dict:
    all_ingredients = []
    for d in drugs:
        all_ingredients.extend(d.active_ingredients)
    
    unique_ingredients = list(set(all_ingredients))
    fda_results = await asyncio.gather(*[fetch_openfda(ing) for ing in unique_ingredients])
    fda_data = {ing: res for ing, res in zip(unique_ingredients, fda_results)}
        
    prompt = f"""You are Agent 4 (Pharmacovigilance). Analyze the OpenFDA data for these active ingredients:
{json.dumps(fda_data, indent=2)}

You must identify:
1. Significant side effects.
2. If multiple active ingredients exist, check for known DRUG-DRUG INTERACTIONS between them based on the text.

Output JSON:
{{
  "side_effects_summary": "Plain language summary of side effects",
  "drug_interactions_summary": "Summary of interactions between the drugs (if multiple), or general interactions to avoid",
  "critical_warnings": ["list of severe warnings"]
}}"""
    res = await groq_client.chat.completions.create(
        model=AGENT_4_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

def compute_suspicion(preflight_score: float, a1_score: float, a2_score: float, a3_score: float) -> dict:
    weighted = (
        preflight_score * 0.35 +
        a1_score        * 0.20 +
        a2_score        * 0.25 +
        a3_score        * 0.20
    )
    
    if weighted <= 0.2:
        ceiling = 100
        floor_risk = None
    elif weighted <= 0.4:
        ceiling = 80
        floor_risk = None
    elif weighted <= 0.6:
        ceiling = 65
        floor_risk = "SUSPICIOUS / HIGH RISK"
    elif weighted <= 0.8:
        ceiling = 45
        floor_risk = "SUSPICIOUS / HIGH RISK"
    else:
        ceiling = 25
        floor_risk = "CRITICAL FAILURE / FAKE"
        
    return {
        "weighted_score": round(weighted, 3),
        "confidence_ceiling": ceiling,
        "risk_floor": floor_risk
    }

async def run_agent_5_verdict(
    symptoms: str, 
    drugs: List[DrugInfo], 
    a1s: list, 
    a2s: list, 
    a3s: list, 
    a4: dict,
    preflight_flags: List[str],
    suspicion_report: dict,
    fast_fail: bool = False
) -> dict:
    drugs_str = "\n".join([f"- {d.brand_name} ({', '.join(d.active_ingredients)}) for {d.stated_therapeutic_use}" for d in drugs])

    prompt = f"""You are Agent 5 — the VerifyMed Safety Advisor. You are the final, authoritative medical-intelligence voice.
You must perform a two-phase adversarial analysis of the drug(s) before returning your final report:

PHASE 1: ADVERSARIAL RED-TEAM REVIEW
Critically examine all the evidence, flags, and registry failures. Write a robust argument (the "investigators_concerns") for why this drug/consignment might be counterfeit, unregistered, or dangerous. Be aggressive: do not gloss over warnings.

PHASE 2: BALANCED MEDICAL VERDICT
Weigh the red-team concerns against any positive matches. Decide the final risk level and confidence score.

MEDICAL-LEGAL RULES (non-negotiable):
- Never use definitive terms like "safe", "100% genuine", or "definitely fake".
- Always recommend the user consult a licensed doctor or pharmacist.
- This tool is for educational and informational purposes only.

PATIENT CONTEXT:
- Reported symptoms: "{symptoms}"
- Drugs submitted: {drugs_str}

{"[FAST-FAIL NOTICE]: Preflight check triggered a CRITICAL mismatch. This drug is highly likely a counterfeit." if fast_fail else ""}

PRE-FLIGHT FLAGS:
{json.dumps(preflight_flags, indent=2)}

SUSPICION CONSTRAINTS:
- Calculated suspicion score: {suspicion_report.get('weighted_score')}
- Confidence score ceiling: {suspicion_report.get('confidence_ceiling')}%
- Required minimum risk level: {suspicion_report.get('risk_floor') or "None"}

RAW AGENT OUTPUTS:
Agent 1 — Registry & Identity: {json.dumps(a1s)}
Agent 2 — Global Intelligence (counterfeits/recalls): {json.dumps(a2s)}
Agent 3 — Science (pharmacological consistency & DB lookup): {json.dumps(a3s)}
Agent 4 — Pharmacovigilance (OpenFDA side effects & interactions): {json.dumps(a4)}

CRITICAL MAS PIN INSTRUCTION:
Because you cannot digitally query the MAS database, you MUST explicitly state in the `patient_summary` that to be 100% sure, the user MUST scratch the silver panel on the box and send the PIN via SMS to the number provided (usually 38120). If they cannot do this or there is no panel, tell them to be extremely wary of the drug.

Output ONLY valid JSON:
{{
  "confidence_score_percentage": 0-100 (Do NOT exceed the ceiling of {suspicion_report.get('confidence_ceiling')}),
  "risk_level": "VERIFIED RECORD" | "SUSPICIOUS / HIGH RISK" | "CRITICAL FAILURE / FAKE" (Must be at least {suspicion_report.get('risk_floor') or 'VERIFIED RECORD'}),
  "investigators_concerns": "Detailed Phase 1 adversarial arguments listing everything suspicious or risky.",
  "patient_summary": "Context-aware summary referencing symptoms, drug findings, and the critical MAS PIN SMS warning.",
  "actionable_steps": ["Specific step 1 based on findings", "Specific step 2"],
  "side_effects_and_interactions": "Specific side effects and interaction warnings from Agent 4 data.",
  "what_to_check_on_pack": "Explicitly tell them to scratch the MAS panel and click the SMS button below.",
  "who_to_contact": "Specific authority, hotline number, or URL."
}}"""

    res = await groq_client.chat.completions.create(
        model=AGENT_5_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    
    verdict = json.loads(res.choices[0].message.content)
    
    # Python-level Hard constraints enforcement
    ceiling = suspicion_report.get('confidence_ceiling', 100)
    verdict["confidence_score_percentage"] = min(
        int(verdict.get("confidence_score_percentage", 100)),
        ceiling
    )
    
    risk_floor = suspicion_report.get('risk_floor')
    if risk_floor:
        risk_order = ["VERIFIED RECORD", "SUSPICIOUS / HIGH RISK", "CRITICAL FAILURE / FAKE"]
        current_risk = verdict.get("risk_level", "VERIFIED RECORD")
        if current_risk in risk_order and risk_floor in risk_order:
            if risk_order.index(current_risk) < risk_order.index(risk_floor):
                verdict["risk_level"] = risk_floor
                
    verdict["suspicion_score"] = suspicion_report.get('weighted_score', 0.0)
    return verdict

import base64
from fastapi import File, UploadFile

@app.post("/ocr")
async def ocr_endpoint(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        base64_image = base64.b64encode(contents).decode('utf-8')
        prompt = """Extract details from this drug package. Output valid JSON:
{
  "brand_name": "string",
  "manufacturer": "string",
  "batch_number": "string",
  "active_ingredients": ["string"],
  "stated_therapeutic_use": "string",
  "nafdac_number": "string (optional, format: A4-XXXXXX or B4-XXXXXX or 04-XXXXXX or C4-XXXXXX)"
}"""
        res = await groq_client.chat.completions.create(
            model=STAGE_0_MODEL,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{file.content_type};base64,{base64_image}"}}]}]
        , temperature=0.1, response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {str(e)}")


@app.post("/chat_intake")
async def chat_intake(req: ChatRequest):
    system_prompt = """You are the VerifyMed Intake Assistant. Your goal is to collect information from the user before verifying their medication.
You need the following for AT LEAST ONE drug (but accept multiple if they mention them):
- Brand Name
- Manufacturer
- Batch Number
- Active Ingredients
- Stated Therapeutic Use
- NAFDAC Number (optional, look for text starting with A4-, B4-, 04-, or C4-)
You ALSO need to ask for:
- The patient's current symptoms.

Be polite, empathetic, and concise. Guide the user on where to find this info on the box.
If you have collected ALL this information for all mentioned drugs and their symptoms, set "status" to "complete" and populate the "extracted_data".
Otherwise, set "status" to "chatting", leave "extracted_data" null, and provide your "reply".

Output ONLY valid JSON:
{
  "status": "chatting" | "complete",
  "reply": "Your message to the user",
  "extracted_data": {
    "patient_symptoms": "string",
    "drugs": [
      {
        "brand_name": "string",
        "manufacturer": "string",
        "batch_number": "string",
        "active_ingredients": ["string"],
        "stated_therapeutic_use": "string",
        "nafdac_number": "string (optional)"
      }
    ]
  }
}"""
    messages = [{"role": "system", "content": system_prompt}] + [{"role": m.role, "content": m.content} for m in req.messages]
    
    res = await groq_client.chat.completions.create(
        model=CHAT_MODEL, messages=messages,
        response_format={"type": "json_object"}, temperature=0.3
    )
    return json.loads(res.choices[0].message.content)


@app.post("/verify")
async def verify_endpoint(req: VerifyRequest):
    if not req.drugs:
        raise HTTPException(status_code=400, detail="No drugs provided")

    # 1. Run Pre-flight
    preflight_res = await run_preflight(req.preflight, req.drugs)
    
    # 2. Tier 1: Hard Fail Path
    if preflight_res.tier == "hard_fail":
        # Run only Agent 2 (Intelligence) and Agent 5 (Verdict)
        a2_tasks = [run_agent_2_intelligence(drug, preflight_res.flags) for drug in req.drugs]
        a2s = await asyncio.gather(*a2_tasks)
        
        # Identity and Science are skipped. Mock their outputs or pass empty ones.
        a1s = [{"manufacturer_registered": False, "registry_match_found": False, "suspicion_agent1": 1.0, "flagged_anomalies": ["Preflight Hard Fail"]}] * len(req.drugs)
        a3s = [{"pharmacologically_consistent": False, "inconsistencies_found": ["Preflight Hard Fail"], "suspicion_agent3": 1.0, "analysis": "Skipped due to preflight hard fail"}] * len(req.drugs)
        
        # Pharmacovigilance is skipped
        a4 = {
            "side_effects_summary": "Skipped due to preflight mismatch",
            "drug_interactions_summary": "Skipped due to preflight mismatch",
            "critical_warnings": ["Preflight Hard Fail"]
        }
        
        # Calculate suspicion — for hard_fail, force all agent scores to 1.0
        # so weighted score always exceeds 0.8 → CRITICAL FAILURE ceiling/floor
        susp_report = compute_suspicion(1.0, 1.0, 1.0, 1.0)
        
        # Run Agent 5
        verdict = await run_agent_5_verdict(
            req.patient_symptoms,
            req.drugs,
            a1s,
            a2s,
            a3s,
            a4,
            preflight_res.flags,
            susp_report,
            fast_fail=True
        )
        
        # Hard enforcement: a physical barcode/batch mismatch is non-negotiable.
        # Override any LLM output that tries to soften the verdict.
        verdict["risk_level"] = "CRITICAL FAILURE / FAKE"
        verdict["confidence_score_percentage"] = min(
            int(verdict.get("confidence_score_percentage", 25)), 25
        )
        
        return {
            "status": "success",
            "tier": "hard_fail",
            "agent_outputs": {
                "agent_preflight": preflight_res.dict(),
                "agent_1_identity": "skipped",
                "agent_2_intelligence": a2s,
                "agent_3_science": "skipped",
                "agent_4_pharmacovigilance": "skipped"
            },
            "verdict": verdict
        }
        
    # 3. Tiers 2 & 3: Normal/Soft Flag Path
    a1_tasks = [run_agent_1_identity(drug, preflight_res.flags) for drug in req.drugs]
    a2_tasks = [run_agent_2_intelligence(drug, preflight_res.flags) for drug in req.drugs]
    a3_tasks = [run_agent_3_science(drug) for drug in req.drugs]
    a4_task = run_agent_4_pharmacovigilance(req.drugs)
    
    # Gather everything in a single parallel block
    a1s, a2s, a3s, a4 = await asyncio.gather(
        asyncio.gather(*a1_tasks),
        asyncio.gather(*a2_tasks),
        asyncio.gather(*a3_tasks),
        a4_task
    )
    
    # Compute suspicion score
    a1_max = max([a.get("suspicion_agent1", 0.0) for a in a1s]) if a1s else 0.0
    a2_max = max([a.get("suspicion_agent2", 0.0) for a in a2s]) if a2s else 0.0
    a3_max = max([a.get("suspicion_agent3", 0.0) for a in a3s]) if a3s else 0.0
    
    susp_report = compute_suspicion(preflight_res.suspicion_preflight, a1_max, a2_max, a3_max)
    
    # Run Agent 5
    verdict = await run_agent_5_verdict(
        req.patient_symptoms,
        req.drugs,
        list(a1s),
        list(a2s),
        list(a3s),
        a4,
        preflight_res.flags,
        susp_report,
        fast_fail=False
    )
    
    return {
        "status": "success",
        "tier": preflight_res.tier,
        "agent_outputs": {
            "agent_preflight": preflight_res.dict(),
            "agent_1_identity": list(a1s),
            "agent_2_intelligence": list(a2s),
            "agent_3_science": list(a3s),
            "agent_4_pharmacovigilance": a4
        },
        "verdict": verdict
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
