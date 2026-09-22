import json
import logging
from django.conf import settings
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def analyze_report_findings(findings_text, purpose_items):
    """
    Calls the Gemini API to compare the inspector's findings against the project's purpose items.
    Returns a list of dicts: [{"purpose_item_id": int, "verdict": str, "reason": str}]
    """
    api_key = getattr(settings, 'GEMINI_API_KEY', None)
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set. Skipping AI analysis.")
        return []

    try:
        client = genai.Client(api_key=api_key)
        
        # Construct the items payload
        items_str = "\n".join([f"- ID: {item.id}, Claimed Description: {item.description}" for item in purpose_items])
        
        prompt = f"""
You are an AI assisting an inspection official. Given the following `Purpose Items` for a government-funded project, and the inspector's free-text `Findings`, determine if the findings indicate that each purpose item matches the claim, is a mismatch (e.g. not done or improperly done), or if it's unclear.

Purpose Items:
{items_str}

Inspector Findings:
{findings_text}

Analyze the findings and provide a strict JSON array where each element matches this schema:
{{
  "purpose_item_id": integer,
  "verdict": "matches" | "mismatch" | "unclear",
  "reason": "Brief explanation based on the findings text"
}}
"""
        response = client.models.generate_content(
            model=getattr(settings, 'GEMINI_CHAT_MODEL', 'gemini-3.8-flash'),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        
        # Parse the JSON response
        try:
            result = json.loads(response.text)
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode Gemini JSON response: {e}")
            return []
            
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return []


def analyze_full_report(report):
    """Use Gemini to classify evidence-backed anomalies across a finalized report."""
    api_key = getattr(settings, 'GEMINI_API_KEY', None)
    if not api_key:
        return []

    try:
        client = genai.Client(api_key=api_key)
        project = report.inspection.project
        payload = {
            "project": project.title,
            "scheme": project.scheme_name,
            "claimed_fund": str(project.fund_utilized_claimed),
            "verified_fund": str(report.fund_utilized_verified),
            "beneficiaries_claimed": report.beneficiaries_claimed_count,
            "beneficiaries_verified": report.beneficiaries_verified_count,
            "ghost_beneficiaries": report.ghost_beneficiaries_count,
            "findings": report.findings or "",
        }
        prompt = f"""You are the NIRIKSHAN inspection anomaly engine.
Analyze ONLY the supplied inspection record. Do not invent facts.
Identify material anomalies supported by the record. Return a JSON array.
Each item must contain:
type: one of fund_mismatch, ghost_beneficiary, purpose_mismatch, location_mismatch, attendance, other
severity: low, medium, or high
reason: concise evidence-based explanation
data: a short statement of the supplied values that support the finding

Record:
{json.dumps(payload, ensure_ascii=False)}
"""
        response = client.models.generate_content(
            model=getattr(settings, 'GEMINI_CHAT_MODEL', 'gemini-3.8-flash'),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        parsed = json.loads(response.text or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception as exc:
        logger.exception("Gemini full report analysis failed: %s", exc)
        return []
