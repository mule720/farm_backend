"""
AI Vision client — uses Claude's vision capability to analyse farm images.

Supported analysis types:
  crop_disease       → pathogen/symptom identification, treatment plan
  pest_identification→ pest species, damage assessment, control measures
  livestock_health   → visible health indicators, condition score, vet actions
  livestock_count    → count animals visible in frame, flag anomalies
  field_survey       → overall crop/field health from drone imagery
  weed_detection     → weed species, coverage estimate, control options
  soil_assessment    → soil colour/texture/structure observations
  general            → open-ended farm observation

Returns a dict with:
  diagnosis, severity, confidence_pct, findings [], recommendations [],
  ai_summary, extra_data {}
"""

import os
import json
import re
import logging

logger = logging.getLogger(__name__)

ANALYSIS_PROMPTS = {
    'crop_disease': """You are an expert agricultural plant pathologist with 20+ years of experience in sub-Saharan African crops.

Analyse this crop/plant image and provide a structured assessment. Respond ONLY with valid JSON in this exact format:
{
  "diagnosis": "Primary identified disease or condition (brief name)",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 85,
  "findings": [
    {"title": "Finding name", "detail": "Detailed observation"}
  ],
  "recommendations": [
    "Specific actionable recommendation 1",
    "Specific actionable recommendation 2"
  ],
  "ai_summary": "2-3 sentence plain-language summary of the situation and urgency",
  "extra_data": {
    "affected_area_estimate": "e.g. 30% of visible plants",
    "likely_cause": "e.g. Fungal infection — Cercospora leaf spot",
    "treatment_products": ["e.g. Mancozeb 80WP", "Copper oxychloride"],
    "time_to_act": "e.g. Within 48 hours"
  }
}""",

    'pest_identification': """You are an expert in agricultural entomology and integrated pest management for African farming systems.

Identify the pest(s) in this image and provide a management plan. Respond ONLY with valid JSON:
{
  "diagnosis": "Pest species or group identified",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 80,
  "findings": [
    {"title": "Identification", "detail": "Species characteristics observed"}
  ],
  "recommendations": [
    "Immediate control action",
    "Preventive measure"
  ],
  "ai_summary": "Brief description of the pest threat and urgency",
  "extra_data": {
    "pest_stage": "e.g. adult/larva/egg",
    "damage_type": "e.g. leaf-chewing, sap-sucking",
    "economic_threshold": "e.g. >5 per plant requires treatment",
    "chemical_control": ["product names"],
    "biological_control": ["natural enemies or biopesticides"]
  }
}""",

    'livestock_health': """You are a senior veterinary AI assistant specialised in farm animal health in sub-Saharan Africa.

Assess the visible health status of the animal(s) in this image. Respond ONLY with valid JSON:
{
  "diagnosis": "Primary health observation or condition",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 75,
  "findings": [
    {"title": "Body condition", "detail": "Observable body condition score and notes"},
    {"title": "Visible symptoms", "detail": "Any signs of disease, injury or distress"}
  ],
  "recommendations": [
    "Veterinary or management action recommended"
  ],
  "ai_summary": "Plain-language health summary for the farmer",
  "extra_data": {
    "body_condition_score": "1-5 scale estimate",
    "estimated_age_group": "e.g. chick/grower/adult",
    "immediate_vet_required": false,
    "likely_conditions": ["e.g. Newcastle disease signs", "nutritional deficiency"]
  }
}""",

    'livestock_count': """You are an automated livestock counting AI system.

Count ALL visible animals in this image. Be precise — count each individual animal. Respond ONLY with valid JSON:
{
  "diagnosis": "Livestock count completed",
  "severity": "none",
  "confidence_pct": 90,
  "findings": [
    {"title": "Count result", "detail": "Number of animals counted and method used"}
  ],
  "recommendations": [
    "Action if count differs significantly from records"
  ],
  "ai_summary": "Count summary with any notable observations",
  "extra_data": {
    "total_counted": 42,
    "species_detected": "e.g. broiler chickens",
    "count_confidence": "high|medium|low",
    "animals_in_distress": 0,
    "notes": "Any observations about animal behaviour or condition"
  }
}""",

    'field_survey': """You are an expert agricultural drone survey analyst specialising in crop health assessment.

Analyse this aerial/field image and produce a field health report. Respond ONLY with valid JSON:
{
  "diagnosis": "Overall field health summary",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 80,
  "findings": [
    {"title": "Zone A — North section", "detail": "Health observations for this zone"},
    {"title": "Problem areas", "detail": "Describe any stressed or diseased patches"}
  ],
  "recommendations": [
    "Priority field action with specific location if possible"
  ],
  "ai_summary": "Executive summary of field health and top priorities",
  "extra_data": {
    "overall_health_score": 72,
    "estimated_healthy_pct": 65,
    "estimated_stressed_pct": 25,
    "estimated_severe_pct": 10,
    "detected_issues": [
      {"issue": "Drought stress", "area_estimate": "15%", "severity": "medium"}
    ],
    "yield_impact_estimate": "e.g. 10-15% reduction if untreated"
  }
}""",

    'weed_detection': """You are an expert in weed science and integrated weed management for small and commercial farms.

Identify weeds in this image and recommend control. Respond ONLY with valid JSON:
{
  "diagnosis": "Primary weed species or weed pressure assessment",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 80,
  "findings": [
    {"title": "Weed species", "detail": "Species identified and their characteristics"}
  ],
  "recommendations": [
    "Mechanical or chemical control recommendation"
  ],
  "ai_summary": "Weed pressure summary and urgency of control",
  "extra_data": {
    "coverage_estimate_pct": 20,
    "competitive_impact": "e.g. High — broadleaf weeds competing for nutrients",
    "herbicides": ["product name — rate — timing"],
    "manual_control": "Hoeing recommendation"
  }
}""",

    'soil_assessment': """You are an expert soil scientist and agronomist.

Assess soil health from this image based on visible colour, texture, structure, and any erosion indicators. Respond ONLY with valid JSON:
{
  "diagnosis": "Soil condition summary",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 65,
  "findings": [
    {"title": "Soil colour", "detail": "Colour observations and what they indicate"},
    {"title": "Structure", "detail": "Visible tilth, compaction, or erosion signs"}
  ],
  "recommendations": [
    "Soil amendment or management recommendation"
  ],
  "ai_summary": "Soil health overview and priority actions",
  "extra_data": {
    "estimated_organic_matter": "e.g. Low — pale colour indicates low OM",
    "drainage_indicator": "good|moderate|poor",
    "erosion_risk": "low|medium|high",
    "suggested_amendments": ["Compost application", "Cover cropping"]
  }
}""",

    'general': """You are an expert agricultural AI advisor for mixed farms in sub-Saharan Africa.

Analyse this farm image and provide observations and recommendations. Respond ONLY with valid JSON:
{
  "diagnosis": "Main observation",
  "severity": "none|low|medium|high|critical",
  "confidence_pct": 75,
  "findings": [
    {"title": "Observation", "detail": "What you see and what it means"}
  ],
  "recommendations": [
    "Practical recommendation for the farmer"
  ],
  "ai_summary": "Overall assessment in plain language",
  "extra_data": {}
}""",
}

FALLBACK_RESPONSE = {
    'diagnosis': 'Unable to analyse image',
    'severity': 'none',
    'confidence_pct': 0,
    'findings': [{'title': 'Analysis failed', 'detail': 'Could not process the image. Ensure it is clear and well-lit.'}],
    'recommendations': ['Please retake the photo in good lighting and try again.'],
    'ai_summary': 'Image analysis could not be completed. Please try again with a clearer image.',
    'extra_data': {},
}


def analyse_image(
    image_url: str,
    analysis_type: str,
    user_description: str = '',
    extra_context: str = '',
) -> dict:
    """
    Call Claude Vision to analyse a farm image.

    :param image_url: Publicly accessible URL of the image
    :param analysis_type: One of the ANALYSIS_PROMPTS keys
    :param user_description: Farmer's own description of what they see
    :param extra_context: Additional context (batch info, crop stage, etc.)
    :returns: Structured dict with diagnosis, severity, findings, etc.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        logger.warning('ANTHROPIC_API_KEY not set — returning stub analysis')
        return _stub_response(analysis_type, user_description)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        system_prompt = ANALYSIS_PROMPTS.get(analysis_type, ANALYSIS_PROMPTS['general'])

        user_parts = []
        if image_url:
            user_parts.append({
                'type': 'image',
                'source': {'type': 'url', 'url': image_url},
            })

        text_content = 'Please analyse this farm image.'
        if user_description:
            text_content += f'\n\nFarmer reports: {user_description}'
        if extra_context:
            text_content += f'\n\nAdditional context: {extra_context}'
        user_parts.append({'type': 'text', 'text': text_content})

        response = client.messages.create(
            model='claude-opus-4-8',
            max_tokens=1500,
            system=system_prompt,
            messages=[{'role': 'user', 'content': user_parts}],
        )

        raw_text = response.content[0].text.strip()
        result = _parse_json_response(raw_text)
        result['ai_model_used'] = 'claude-opus-4-8'
        return result

    except Exception as exc:
        logger.error('Vision analysis error: %s', exc)
        return {**FALLBACK_RESPONSE, 'extra_data': {'error': str(exc)}}


def _parse_json_response(text: str) -> dict:
    """Extract JSON from the AI response, tolerating markdown code fences."""
    # Strip code fences if present
    cleaned = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    cleaned = re.sub(r'\s*```$', '', cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON block
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return FALLBACK_RESPONSE


def _stub_response(analysis_type: str, description: str) -> dict:
    """Return a realistic stub when no API key is configured (dev mode)."""
    stubs = {
        'crop_disease': {
            'diagnosis': 'Cercospora Leaf Spot (Gray leaf spot)',
            'severity': 'medium',
            'confidence_pct': 82,
            'findings': [
                {'title': 'Leaf symptoms', 'detail': 'Circular to elongated tan lesions with gray centers and brown borders visible on lower leaves.'},
                {'title': 'Spread pattern', 'detail': 'Lesions present on approximately 25% of leaf surface on affected plants.'},
            ],
            'recommendations': [
                'Apply Mancozeb 80WP at 2.5kg/ha — repeat every 10-14 days.',
                'Improve air circulation by reducing plant density if possible.',
                'Remove and destroy severely infected leaves.',
                'Avoid overhead irrigation to reduce leaf wetness duration.',
            ],
            'ai_summary': 'The crop shows signs of Cercospora leaf spot, a fungal disease favoured by warm humid conditions. With medium severity, prompt fungicide application is recommended to prevent further spread and significant yield loss.',
            'extra_data': {
                'affected_area_estimate': '~25% of plants showing symptoms',
                'likely_cause': 'Cercospora zeae-maydis or similar Cercospora species',
                'treatment_products': ['Mancozeb 80WP', 'Propiconazole 25EC', 'Azoxystrobin'],
                'time_to_act': 'Within 3-5 days',
            },
        },
        'livestock_health': {
            'diagnosis': 'Mild respiratory distress — monitor closely',
            'severity': 'low',
            'confidence_pct': 70,
            'findings': [
                {'title': 'Body condition', 'detail': 'Body condition score appears 2.5-3/5 — slightly below optimum. Feather/coat condition is acceptable.'},
                {'title': 'Posture & behaviour', 'detail': 'Some animals appear slightly hunched — may indicate discomfort or early respiratory issue.'},
            ],
            'recommendations': [
                'Improve ventilation in housing — check for ammonia build-up.',
                'Review water intake records — inadequate water worsens respiratory conditions.',
                'Consult a vet if symptoms persist beyond 48 hours or more than 5% of flock is affected.',
                'Check feed quality and ensure vitamin E/selenium supplementation is adequate.',
            ],
            'ai_summary': 'The animals show mild signs that could indicate early respiratory stress or nutritional suboptimality. Immediate vet attention is not required but monitoring and ventilation improvement are recommended.',
            'extra_data': {
                'body_condition_score': '2.5-3/5',
                'estimated_age_group': 'grower',
                'immediate_vet_required': False,
                'likely_conditions': ['Mild respiratory irritation', 'Nutritional deficiency'],
            },
        },
        'livestock_count': {
            'diagnosis': 'Livestock count completed — 47 animals detected',
            'severity': 'none',
            'confidence_pct': 91,
            'findings': [
                {'title': 'Count result', 'detail': '47 individual animals identified in the frame using density estimation.'},
                {'title': 'Distribution', 'detail': 'Animals appear evenly distributed across the pen — no crowding stress observed.'},
            ],
            'recommendations': [
                'Compare count with batch records — discrepancy >3% requires investigation.',
                'Schedule next count in 7 days to establish movement baseline.',
            ],
            'ai_summary': '47 animals detected in this image with high confidence. No signs of stress or crowding visible. Regular automated counts are recommended to detect unauthorized stock movement early.',
            'extra_data': {
                'total_counted': 47,
                'species_detected': 'Broiler chickens',
                'count_confidence': 'high',
                'animals_in_distress': 0,
                'notes': 'Clear image, good count confidence',
            },
        },
        'field_survey': {
            'diagnosis': 'Moderate crop stress — drought and possible early blight detected',
            'severity': 'medium',
            'confidence_pct': 78,
            'findings': [
                {'title': 'Overall health', 'detail': 'Approximately 60% of the field shows healthy green canopy. 25% shows drought stress (yellowing). 15% shows darkened/blighted patches.'},
                {'title': 'Problem zones', 'detail': 'North-east corner shows most severe stress — likely related to drainage patterns or soil variability.'},
            ],
            'recommendations': [
                'Prioritize irrigation to the north-east quadrant — increase frequency by 20%.',
                'Scout for early blight (Alternaria) in the darkened patches — apply chlorothalonil if confirmed.',
                'Consider soil moisture sensors in the stressed zones.',
                'Reassess in 7-10 days after irrigation adjustment.',
            ],
            'ai_summary': 'The drone survey reveals a field under moderate stress, primarily from moisture deficit in the north-east section. Early disease signs are also visible. Targeted irrigation and disease management in the next 5-7 days could prevent significant yield loss.',
            'extra_data': {
                'overall_health_score': 65,
                'estimated_healthy_pct': 60,
                'estimated_stressed_pct': 25,
                'estimated_severe_pct': 15,
                'detected_issues': [
                    {'issue': 'Drought stress', 'area_estimate': '25%', 'severity': 'medium'},
                    {'issue': 'Early blight suspect', 'area_estimate': '15%', 'severity': 'medium'},
                ],
                'yield_impact_estimate': '15-25% reduction if untreated within 10 days',
            },
        },
    }
    base = stubs.get(analysis_type, {
        'diagnosis': 'Farm image analysed',
        'severity': 'low',
        'confidence_pct': 70,
        'findings': [{'title': 'General observation', 'detail': description or 'Image received and processed.'}],
        'recommendations': ['Continue monitoring and report any changes.'],
        'ai_summary': 'Image analysis completed. Please add your ANTHROPIC_API_KEY for full AI-powered analysis.',
        'extra_data': {'note': 'Configure ANTHROPIC_API_KEY in .env for live AI analysis'},
    })
    base['ai_model_used'] = 'stub-dev'
    return base
