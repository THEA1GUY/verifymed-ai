import os
import json
import httpx
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
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
AGENT_2_MODEL = "llama-3.3-70b-versatile" 
AGENT_3_MODEL = "llama-3.3-70b-versatile"
AGENT_4_MODEL = "llama-3.3-70b-versatile"
AGENT_5_MODEL = "llama-3.3-70b-versatile"
CHAT_MODEL = "llama-3.3-70b-versatile"

class DrugInfo(BaseModel):
    brand_name: str
    manufacturer: str
    batch_number: str
    active_ingredients: List[str]
    stated_therapeutic_use: str

class VerifyRequest(BaseModel):
    patient_symptoms: str
    drugs: List[DrugInfo]

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

async def run_agent_1_identity(drug: DrugInfo) -> dict:
    nafdac_query = f"site:greenbook.nafdac.gov.ng {drug.brand_name} {drug.manufacturer}"
    nafdac_results = await search_tavily(nafdac_query)
    who_results = await check_who_registry(drug.brand_name, drug.manufacturer)
    
    prompt = f"""You are Agent 1 (Identity). Analyze web search results for the drug: {drug.brand_name} by {drug.manufacturer}.
NAFDAC Search Results: {nafdac_results}
WHO Search Results: {who_results}
Output JSON:
{{
  "manufacturer_registered": true/false,
  "registry_match_found": true/false,
  "flagged_anomalies": ["list of anomalies or 'None'"]
}}"""
    res = await groq_client.chat.completions.create(
        model=AGENT_1_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

async def run_agent_2_intelligence(drug: DrugInfo) -> dict:
    query = f"{drug.brand_name} {drug.manufacturer} {drug.batch_number} counterfeit OR fake OR recall OR warning"
    news_results = await search_tavily(query)
    
    prompt = f"""You are Agent 2 (Intelligence). Analyze global search results for warnings/recalls/fakes for: {drug.brand_name} (Batch: {drug.batch_number}).
Results: {news_results}
Output JSON:
{{
  "counterfeit_alerts_found": true/false,
  "recall_notices_found": true/false,
  "details": "summary of findings"
}}"""
    res = await groq_client.chat.completions.create(
        model=AGENT_2_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

async def run_agent_3_science(drug: DrugInfo) -> dict:
    ingredients = ", ".join(drug.active_ingredients)
    prompt = f"""You are Agent 3 (Science). You are an expert pharmacologist and counterfeit detector.
Examine the active ingredients and cross-reference them with the drug's stated therapeutic use and typical brand formulation.
Active Ingredients: {ingredients}
Intended Use: {drug.stated_therapeutic_use}

CRITICAL COUNTERFEIT CHECK:
If the stated active ingredients are complete nonsense (e.g. "trash", "chalk"), do not match the typical formulation of the brand, or do not match the intended use at all, THIS IS A MASSIVE RED FLAG THAT THE DRUG IS A COUNTERFEIT. Do NOT just say "it is not for the stated use" — explicitly conclude that the physical packaging is likely fake because a real drug of this type would never contain these ingredients.

Output JSON:
{{
  "pharmacologically_consistent": true/false,
  "inconsistencies_found": ["list"],
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
    
    fda_data = {}
    for ing in set(all_ingredients):
        fda_data[ing] = await fetch_openfda(ing)
        
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

async def run_agent_5_verdict(symptoms: str, drugs: List[DrugInfo], a1s: list, a2s: list, a3s: list, a4: dict) -> dict:
    drugs_str = "\n".join([f"- {d.brand_name} ({', '.join(d.active_ingredients)}) for {d.stated_therapeutic_use}" for d in drugs])

    prompt = f"""You are Agent 5 — the VerifyMed Safety Advisor. You are the final, authoritative medical-intelligence voice.

You have received raw structured outputs from four specialist agents. Read them carefully and reason from the evidence — do NOT summarise generically. Draw your own conclusions.

MEDICAL-LEGAL RULES (non-negotiable):
- Never use definitive terms like "safe", "100% genuine", or "definitely fake".
- Always recommend the user consult a licensed doctor or pharmacist.
- This tool is for educational and informational purposes only.

PATIENT CONTEXT:
- Reported symptoms: "{symptoms}"
- Drugs submitted: {drugs_str}
Explain whether the drugs are pharmacologically appropriate for the reported symptoms (e.g. "Artemether/Lumefantrine is commonly used to treat malaria, which is consistent with your reported fever and chills").

RAW AGENT OUTPUTS (reason from these directly):
Agent 1 — Registry & Identity: {json.dumps(a1s)}
Agent 2 — Global Intelligence (counterfeits/recalls): {json.dumps(a2s)}
Agent 3 — Science (pharmacological consistency): {json.dumps(a3s)}
Agent 4 — Pharmacovigilance (OpenFDA side effects & interactions): {json.dumps(a4)}

REASONING GUIDANCE:
- If Agent 1 shows no registry match for any drug, that is strong evidence it may be unregistered/fake.
- If Agent 2 found active counterfeit alerts or recalls, that is a serious safety signal.
- If Agent 3 found pharmacological inconsistency (e.g. ingredients are nonsense, don't match the brand, or don't match the disease), DO NOT just advise the patient they are taking the wrong medicine. This means the physical box they are holding has fake text printed on it! You MUST treat this as a CRITICAL FAILURE / FAKE.
- Weight all three signals together to decide `risk_level` and `confidence_score_percentage`.
- `confidence_score_percentage` = your assessed probability (0–100) that this drug is genuine and appropriate.
- `risk_level` must be exactly one of: "VERIFIED RECORD", "SUSPICIOUS / HIGH RISK", or "CRITICAL FAILURE / FAKE".

CRITICAL MAS PIN INSTRUCTION:
Because you cannot digitally query the MAS database, you MUST explicitly state in the `patient_summary` that to be 100% sure, the user MUST scratch the silver panel on the box and send the PIN via SMS to the number provided (usually 38120). If they cannot do this or there is no panel, tell them to be extremely wary of the drug.

Output ONLY valid JSON:
{{
  "confidence_score_percentage": 85,
  "risk_level": "VERIFIED RECORD",
  "patient_summary": "Context-aware summary referencing symptoms, drug findings, and the critical MAS PIN SMS warning.",
  "actionable_steps": ["Specific step 1 based on agent findings", "Specific step 2"],
  "side_effects_and_interactions": "Specific side effects and interaction warnings from Agent 4 data.",
  "what_to_check_on_pack": "Explicitly tell them to scratch the MAS panel and click the SMS button below.",
  "who_to_contact": "Specific authority, hotline number, or URL."
}}"""

    res = await groq_client.chat.completions.create(
        model=AGENT_5_MODEL, messages=[{"role": "system", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.1
    )
    return json.loads(res.choices[0].message.content)

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
  "stated_therapeutic_use": "string"
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
        "stated_therapeutic_use": "string"
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

    a1s, a2s, a3s = [], [], []
    # Run all 3 agents for all drugs in parallel across drugs
    tasks = [
        asyncio.gather(
            run_agent_1_identity(drug),
            run_agent_2_intelligence(drug),
            run_agent_3_science(drug)
        )
        for drug in req.drugs
    ]
    results = await asyncio.gather(*tasks)
    for a1, a2, a3 in results:
        a1s.append(a1)
        a2s.append(a2)
        a3s.append(a3)

    a4 = await run_agent_4_pharmacovigilance(req.drugs)
    verdict = await run_agent_5_verdict(req.patient_symptoms, req.drugs, a1s, a2s, a3s, a4)

    return {
        "status": "success",
        "agent_outputs": {
            "agent_1_identity": a1s,
            "agent_2_intelligence": a2s,
            "agent_3_science": a3s,
            "agent_4_pharmacovigilance": a4
        },
        "verdict": verdict
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
