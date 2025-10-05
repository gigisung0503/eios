import requests
import time
import re
import json
import logging
from typing import List, Dict, Any, Tuple
from src.models.signal import RawSignal, ProcessedSignal, ProcessedSignalID, db

logger = logging.getLogger("signal_processor")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
class SignalProcessor:
    def __init__(self):
        """
        Initialize the signal processor.

        This method sets up configuration for calling an AI model to evaluate
        incoming signals. It supports multiple providers via environment
        variables. The following environment variables control the behaviour:

        * ``AI_PROVIDER`` – optional, one of ``openai``, ``deepseek`` or ``local``.
          Defaults to ``openai``.
        * ``OPENAI_API_KEY`` / ``DEEPSEEK_API_KEY`` / ``LOCAL_LLM_API_KEY`` – API
          keys used for authentication. For a local LLM that does not require a
          key, this may be omitted.
        * ``OPENAI_API_BASE`` / ``DEEPSEEK_API_BASE`` / ``LOCAL_LLM_API_BASE`` –
          base URL for the API endpoint. For local providers, this should
          include the scheme and hostname (e.g. ``http://localhost:8000``).
        * ``AI_MODEL`` – optional, model name to use. Defaults to ``gpt-4``.

        The processor also defines a risk evaluation prompt used to query the
        model. Country and hazard extraction prompts are no longer used as the
        evaluation now happens in a single request that assesses whether a
        piece of information constitutes a public health signal.
        """
        import os

        # Provider selection (default openai). Allow override via UserConfig (AI_PROVIDER).
        self.provider = os.getenv('AI_PROVIDER', 'openai').lower()

        # Prepare default API key and base for each provider from environment variables.
        provider_defaults = {
            'openai': {
                'api_key': os.getenv('OPENAI_API_KEY'),
                'api_base': os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
            },
            'deepseek': {
                'api_key': os.getenv('DEEPSEEK_API_KEY'),
                'api_base': os.getenv('DEEPSEEK_API_BASE', 'https://api.deepseek.com/v1')
            },
            'local': {
                'api_key': os.getenv('LOCAL_LLM_API_KEY'),
                'api_base': os.getenv('LOCAL_LLM_API_BASE', 'http://localhost:8000')
            }
        }

        # Pull overrides from UserConfig if available (requires application context). These overrides allow
        # end‑users to configure which provider to use, the API key/base for that provider, and other
        # optional settings like the model name and risk evaluation prompt. We query keys individually
        # so that missing entries do not raise exceptions. If querying outside of an application context
        # fails, all config values remain None and defaults will be used.
        from src.models.signal import UserConfig  # imported here to avoid circular import issues
        cfg_provider = None
        prompt_config = None
        model_config = None
        # Per‑provider config containers
        cfg_keys = {
            'openai': {'api_key': None, 'api_base': None},
            'deepseek': {'api_key': None, 'api_base': None},
            'local': {'api_key': None, 'api_base': None}
        }
        try:
            # Provider override
            provider_entry = UserConfig.query.filter_by(key='AI_PROVIDER').first()
            if provider_entry and provider_entry.value:
                cfg_provider = provider_entry.value.lower()

            # Model override
            model_entry = UserConfig.query.filter_by(key='AI_MODEL').first()
            model_config = model_entry.value if model_entry else None

            # Risk evaluation prompt override
            prompt_entry = UserConfig.query.filter_by(key='risk_evaluation_prompt').first()
            prompt_config = prompt_entry.value if prompt_entry else None

            # Load API keys and bases for each provider if configured
            for prov_key, prov_name in [('OPENAI', 'openai'), ('DEEPSEEK', 'deepseek'), ('LOCAL_LLM', 'local')]:
                key_entry = UserConfig.query.filter_by(key=f'{prov_key}_API_KEY').first()
                base_entry = UserConfig.query.filter_by(key=f'{prov_key}_API_BASE').first()
                cfg_keys[prov_name]['api_key'] = key_entry.value if key_entry else None
                cfg_keys[prov_name]['api_base'] = base_entry.value if base_entry else None
        except Exception:
            # On any error (likely outside of app context) leave config values as None
            cfg_provider = None
            model_config = None
            prompt_config = None

        # Determine final provider: config override > env default
        if cfg_provider:
            self.provider = cfg_provider

        # Determine API key and base for the active provider. Prefer config override for that provider,
        # then environment default.
        defaults_for_provider = provider_defaults.get(self.provider, provider_defaults['openai'])
        prov_cfg = cfg_keys.get(self.provider, {})
        self.api_key = prov_cfg.get('api_key') if prov_cfg.get('api_key') is not None else defaults_for_provider.get('api_key')
        self.api_base = prov_cfg.get('api_base') if prov_cfg.get('api_base') is not None else defaults_for_provider.get('api_base')

        # Model name: config override > env default > hardcoded
        self.model = model_config if model_config else os.getenv('AI_MODEL', 'gpt-4')

        # Rate limiting between calls (seconds)
        self.rate_limit_sleep_sec = 2

        # Text columns to combine for processing
        self.text_columns = [
            "originalTitle", "title",
            "translatedDescription", "translatedAbstractiveSummary", "abstractiveSummary"
        ]

        # Deprecated prompts for country and hazard extraction (no longer used)
        self.country_prompt = None
        self.hazard_prompt = None

        # Default risk evaluation prompt (used if not overridden by config)
        default_prompt = (
            "You are a public health intelligence analyst.\n"
            "Task: Analyze raw information (news, social media, reports, summaries) in any language and determine if it likely represents a public health SIGNAL.\n\n"
            "Definition: A SIGNAL is new or unusual information that may indicate a potential acute risk to human health and warrants further verification.\n\n"
            "Consider as SIGNAL if any apply:\n"
            "- Outbreaks or clusters of infectious disease\n"
            "- Unusual symptoms, unknown etiology, or rapidly spreading illness\n"
            "- Significant rise in morbidity/mortality or hospital burden\n"
            "- Events in displaced populations, conflict zones, or disaster-affected areas\n"
            "- Health system impact (e.g., HCW infections, medicine shortages)\n"
            "- Reemerging diseases, VPD outbreaks, AMR threats\n"
            "- Food/waterborne outbreaks or zoonoses with human exposure\n"
            "- Natural or man-made disasters affecting health (floods, landslides, industrial spills)\n"
            "- International spread potential, travel/trade restrictions, or reputational risk to WHO/authorities\n\n"
            "Do NOT consider as SIGNAL:\n"
            "- Routine seasonal illness patterns unless unusually intense\n"
            "- Purely political/economic/social unrest with no health consequence\n"
            "- Commentary/editorials with no factual reports\n"
            "- Events resolved/controlled with no further risk\n"
            "- Scientific findings without immediate health implications\n"
            "- Information that does not indicate a potential acute risk to human health\n\n"
            "Output format:\n"
            "- Use ||| as a separator between fields in the output.\n"
            "example of output as follows: \n"
            "India ||| Yes ||| The severe rainfall in Vijayawada has caused significant waterlogging and resulted in a fatality, indicating a potential acute risk to human health. The situation involves natural disaster elements with potential health impacts due to flooding. |||environmental (flooding).\n\n"
            "Rules:\n"
            "- Use canonical country names when possible; subnational names allowed if country unknown.\n"
            "- is Signal MUST be exactly \"Yes\" or \"No\" (default to \"No\" if uncertain).\n"
            "- Keep justification short (1 sentence).\n"
            "- Health Hazard Types: Use WHO standard terms (e.g., \"COVID-19\", \"Dengue\", \"Malaria\").\n"
            "TEXT TO ANALYZE:\n"
            "{text}"
        )

        # Use prompt override from UserConfig if available
        self.risk_evaluation_prompt = prompt_config if prompt_config else default_prompt

    def ask_ai(self, prompt: str) -> str:
        """
        Make an API call to the configured language model provider.

        The request is sent to ``self.api_base`` with a ``/chat/completions``
        path, mirroring the OpenAI Chat API. The payload includes the
        configured model, the user prompt, and sensible defaults for
        temperature and top-p. Authentication headers are included when an
        API key is available. If an error occurs, it is logged and an empty
        string is returned.

        :param prompt: The content to send to the model
        :return: The text returned by the model, or an empty string on error
        """
        # Determine API key and headers based on provider configuration
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            # Use Bearer token for providers that require it
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Assemble the request payload. Providers compatible with the OpenAI
        # Chat API should accept this structure; if not, further adaptation
        # may be required for specific providers.
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "top_p": 0.95,
        }

        # Compose the endpoint URL
        endpoint = f"{self.api_base.rstrip('/')}/chat/completions"

        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            # Different providers may structure the response differently. Attempt to
            # extract the assistant's message content in a robust way.
            if isinstance(data, dict):
                # OpenAI-like structure
                choices = data.get("choices")
                if choices and isinstance(choices, list):
                    message = choices[0].get("message")
                    if message and isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str):
                            return content.strip()
                # DeepSeek might return answer in a different field (e.g. 'answer')
                if "answer" in data and isinstance(data["answer"], str):
                    return data["answer"].strip()
            logger.error("AI API: Unexpected response format")
        except Exception as e:
            logger.error(f"AI API ERROR: {e}")
        return ""

    def _ensure_json_or_reprompt(self, first_text: str) -> str:
        import json, re
        logger.info("AI raw response (attempt 1): %s", first_text)
        def extract_json_blob(txt: str):
            m = re.search(r'(\{.*\})', txt, re.DOTALL)
            if not m: 
                return None
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
        obj = extract_json_blob(first_text)
        if obj and all(k in obj for k in ("countries","is_signal","justification","hazard_types")):
            return json.dumps(obj, ensure_ascii=False)
        followup = ("Return ONLY a single JSON object with exactly these keys and nothing else: "
                    '{"countries":["..."],"is_signal":"Yes|No","justification":"..."},"hazard_types":["..."]')
        try:
            second = self.client.responses.create(model=self.model, input=[{"role":"user","content": followup}])
            second_text = self._extract_text(second)
            logger.info("AI raw response (attempt 2): %s", second_text)
            obj2 = extract_json_blob(second_text)
            if obj2 and all(k in obj2 for k in ("countries","is_signal","justification","hazard_types")):
                return json.dumps(obj2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error during JSON re-prompt: %s", e)
        return first_text

    def _ensure_json_or_reprompt(self, first_text: str) -> str:
        import json, re
        logger.info("AI raw response (attempt 1): %s", first_text)
        def extract_json_blob(txt: str):
            m = re.search(r'(\{.*\})', txt, re.DOTALL)
            if not m: 
                return None
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
        obj = extract_json_blob(first_text)
        if obj and all(k in obj for k in ("countries","is_signal","justification","hazard_types")):
            return json.dumps(obj, ensure_ascii=False)
        followup = ("Return ONLY a single JSON object with exactly these keys and nothing else: "
                    '{"countries":["..."],"is_signal":"Yes|No","justification":"...","hazard_types":["..."]}')
        try:
            second = self.client.responses.create(model=self.model, input=[{"role":"user","content": followup}])
            second_text = self._extract_text(second)
            logger.info("AI raw response (attempt 2): %s", second_text)
            obj2 = extract_json_blob(second_text)
            if obj2 and all(k in obj2 for k in ("countries","is_signal","justification","hazard_types")):
                return json.dumps(obj2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error during JSON re-prompt: %s", e)
        return first_text

    def parse_ai_response(self, text: str) -> Tuple[str, str, str, str]:
        """
        Parse the AI response into (countries, is_signal, justification, hazards).

        Handles three formats robustly, in this order:
          1) JSON (keys: country_list or countries, is_signal, justification, hazard_types or hazards)
          2) Triple-bar sections: countries ||| yes/no ||| justification ||| hazards
          3) Labeled prose using ":" and "-" (e.g. "Whether the information is a potential SIGNAL: Yes - A short justification: ... - Optional: suggested hazard type: ...")
        """
        if not text:
            return "", "No", "", ""

        # -------- 1) JSON fallback --------
        # Try to extract a JSON object if present
        try:
            json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            if json_match:
                obj = json.loads(json_match.group(1))
                countries = obj.get("country_list") or obj.get("countries") or ""
                if isinstance(countries, list):
                    countries = ", ".join([str(c).strip() for c in countries if str(c).strip()])
                hazards = obj.get("hazard_types") or obj.get("hazards") or ""
                if isinstance(hazards, list):
                    hazards = ", ".join([str(h).strip() for h in hazards if str(h).strip()])
                is_signal = str(obj.get("is_signal") or obj.get("signal") or "").strip()
                # normalize yes/no
                is_signal = "Yes" if str(is_signal).lower() in {"yes","true","y","1"} else ("No" if str(is_signal).lower() in {"no","false","n","0"} else "")
                justification = obj.get("justification") or obj.get("rationale") or ""
                return countries.strip(), (is_signal or "No"), str(justification).strip(), str(hazards).strip()
        except Exception:
            pass

        # -------- 2) Triple-bar sections --------
        if "|||" in text:
            parts = [p.strip() for p in text.split("|||")]
            parts = (parts + ["", "", "", ""])[:4]
            # strip leading labels like "Countries:"
            def strip_label(s: str) -> str:
                if ":" in s:
                    return s.split(":", 1)[-1].strip()
                return s.strip()
            countries = strip_label(parts[0])
            fp = strip_label(parts[1]).split()
            token = (fp[0] if fp else "").lower()
            if token.startswith("yes"):
                is_signal = "Yes"
            elif token.startswith("no"):
                is_signal = "No"
            else:
                low = parts[1].lower()
                is_signal = "Yes" if "yes" in low else ("No" if "no" in low else "No")
            justification = strip_label(parts[2])
            hazards = strip_label(parts[3])
            return countries, is_signal, justification, hazards
        # -------- 3) Labeled prose --------
        # Normalize spaces and separators: turn " - " and " — " into newlines to ease matching.
        norm = re.sub(r"\s*[-–—]\s*", "\n", text)
        # Patterns for keys
        key_patterns = {
            "countries": r"(?:countries|expected\s*countr(?:y|ies)|impacted\s*countries?)\s*:\s*(.+)",
            "signal": r"(?:whether\s+the\s+information\s+is\s+(?:a\s+)?potential\s+signal|potential\s+signal|signal)\s*:\s*(Yes|No|[A-Za-z]+)",
            "justification": r"(?:short\s+justification|justification|rationale)\s*:\s*(.+)",
            "hazards": r"(?:hazard(?:\s*type)?s?|suggested\s+hazard\s*type)\s*:\s*(.+)",
        }
        def find_val(pat: str) -> str:
            m = re.search(pat, norm, re.IGNORECASE)
            return m.group(1).strip() if m else ""

        countries = find_val(key_patterns["countries"])
        is_signal_raw = find_val(key_patterns["signal"])
        #logger.info(f"Extracted is_signal_raw: {is_signal_raw}")
        if is_signal_raw:
            is_signal = "Yes" if is_signal_raw.lower().startswith(("y","t")) else ("No" if is_signal_raw.lower().startswith(("n","f")) else "No")
        else:
            # last resort: any 'yes'/'no' near "signal"
            sig_hint = re.search(r"signal[^:]{0,40}:\s*([A-Za-z]+)", norm, re.IGNORECASE)
            if sig_hint:
                token = sig_hint.group(1).lower()
                is_signal = "Yes" if token.startswith(("y","t")) else ("No" if token.startswith(("n","f")) else "No")
            else:
                is_signal = "No"

        justification = find_val(key_patterns["justification"])
        hazards = find_val(key_patterns["hazards"])

        return countries, is_signal, justification, hazards

    def extract_score_and_flag(self, text: str) -> Tuple[int, int, int, str]:
        """
        Extract vulnerability score, coping score, total score, and signal flag from AI response.
        """
        # Match patterns like: "Vulnerability score: -4, Coping score: 2, Total: -2"
        score_match = re.search(
            r'(?i)vulnerability.*?(-?\d+).*?coping.*?(\d+).*?total.*?(-?\d+)', text)
        if score_match:
            v_score = int(score_match.group(1))
            c_score = int(score_match.group(2))
            total = int(score_match.group(3))
        else:
            # Try alternative pattern
            total_match = re.search(r'(?i)total.*?score.*?(-?\d+)', text)
            total = int(total_match.group(1)) if total_match else None
            v_score = c_score = None

        is_signal = "Yes" if total is not None and -7 <= total <= 0 else "No"
        return v_score, c_score, total, is_signal

    def combine_text_fields(self, article: Dict[str, Any]) -> str:
        """
        Combine relevant text fields from an article for processing.
        """
        text_parts = []
        for field in self.text_columns:
            value = article.get(field, "")
            if value and isinstance(value, str):
                text_parts.append(value.strip())
        
        return " ".join(text_parts)

    def is_already_processed(self, rss_item_id: str) -> bool:
        """
        Check if a signal has already been processed.
        """
        return ProcessedSignalID.query.filter_by(rss_item_id=rss_item_id).first() is not None

    def mark_as_processed(self, rss_item_id: str):
        """
        Mark a signal as processed to avoid reprocessing.
        """
        if not self.is_already_processed(rss_item_id):
            processed_id = ProcessedSignalID(rss_item_id=rss_item_id)
            db.session.add(processed_id)
            db.session.commit()

    def save_raw_signal(self, article: Dict[str, Any]) -> RawSignal:
        """
        Save raw signal data to database.
        """
        rss_item_id = str(article.get('id', ''))
        combined_text = self.combine_text_fields(article)
        
        # Check if already exists
        existing = RawSignal.query.filter_by(rss_item_id=rss_item_id).first()
        if existing:
            return existing
        
        raw_signal = RawSignal(
            rss_item_id=rss_item_id,
            original_title=article.get('originalTitle', ''),
            title=article.get('title', ''),
            translated_description=article.get('translatedDescription', ''),
            translated_abstractive_summary=article.get('translatedAbstractiveSummary', ''),
            abstractive_summary=article.get('abstractiveSummary', ''),
            combined_text=combined_text
        )
        
        db.session.add(raw_signal)
        db.session.commit()
        return raw_signal

    def process_signal(self, raw_signal: RawSignal, is_pinned: bool = False) -> ProcessedSignal:
        """
        Process a single signal using AI evaluation.

        This method now performs a single call to the AI model using the
        consolidated risk evaluation prompt. It no longer performs
        separate country or hazard extraction. The AI is expected to return a
        response formatted as described in ``self.risk_evaluation_prompt``:

        ``
        Yes or No (is it a SIGNAL); Countries: [list]; Justification: [text]; Hazard type: [text] ||||
        ``

        The parts are separated by ``||||``. Parsing extracts the signal flag,
        country list, justification, and hazard type. These values populate
        the ``ProcessedSignal`` record. Vulnerability, coping and total
        risk scores are set to ``None`` because they are no longer part of
        the consolidated evaluation.
        """
        logger.info(f"Processing signal: {raw_signal.rss_item_id}")
        #logger.info(f" signal: {raw_signal.combined_text}")
        #logger.info(f"processed: {ProcessedSignal.status}")
        #logger.info(f"processed: {ProcessedSignal.__tablename__}")
        
        # Perform a single AI call for risk evaluation
        risk_response = self.ask_ai(
            self.risk_evaluation_prompt.format(text=raw_signal.combined_text))

        # Default values
        extracted_countries = ""
        extracted_hazards = ""
        justification = ""
        is_signal = "No"
        v_score = c_score = total = None

        # Parse the response if present
        if risk_response:
            try:
                # Split the response on the triple‑bar delimiter defined in the risk evaluation prompt ("|||").
                # The expected order of fields is: countries ||| is_signal ||| justification ||| hazard type.
                # Providers sometimes include labels like "Countries:" or "Hazard type:" in each segment. Those
                # prefixes are stripped before assigning the values. Missing segments default to empty strings.
                raw_parts = [p.strip() for p in risk_response.split("|||")]
                # Prepare an array of four strings to hold the parsed segments
                parts: List[str] = ["", "", "", ""]
                for idx, part in enumerate(raw_parts[:4]):
                    parts[idx] = part

                # Segment 0: list of countries (may include a label before a colon)
                countries_part = parts[0]
                if countries_part:
                    if ':' in countries_part:
                        countries_part = countries_part.split(':', 1)[-1]
                    extracted_countries = countries_part.strip()

                # Segment 1: Yes/No indicator (may include a label before a colon)
                flag_part = parts[1]
                if flag_part:
                    token = flag_part
                    if ':' in token:
                        token = token.split(':', 1)[-1]
                    # Only look at the first token to determine yes/no
                    token = token.strip().split()[0] if token.strip() else ""
                    token_lower = token.lower()
                    if token_lower.startswith('yes'):
                        is_signal = 'Yes'
                    elif token_lower.startswith('no'):
                        is_signal = 'No'
                    else:
                        # Fallback: search for "yes" or "no" anywhere in the segment
                        if 'yes' in flag_part.lower():
                            is_signal = 'Yes'
                        elif 'no' in flag_part.lower():
                            is_signal = 'No'

                # Segment 2: justification text
                justification_part = parts[2]
                if justification_part:
                    if ':' in justification_part:
                        justification_part = justification_part.split(':', 1)[-1]
                    justification = justification_part.strip()

                # Segment 3: hazard type
                hazard_part = parts[3]
                if hazard_part:
                    if ':' in hazard_part:
                        hazard_part = hazard_part.split(':', 1)[-1]
                    extracted_hazards = hazard_part.strip()

            except Exception as e:
                # Log and continue on any parsing error – leave defaults in place
                logger.error(f"Error parsing risk response: {e}")

        # risk_signal_assessment stores the raw AI output for transparency
        risk_assessment_text = risk_response

        # Create processed signal
        processed_signal = ProcessedSignal(
            rss_item_id=raw_signal.rss_item_id,
            extracted_countries=extracted_countries,
            extracted_hazards=extracted_hazards,
            risk_signal_assessment=risk_assessment_text,
            vulnerability_score=v_score,
            coping_score=c_score,
            total_risk_score=total,
            is_signal=is_signal,
            is_pinned=is_pinned,
            raw_signal_id=raw_signal.id
        )
        
        db.session.add(processed_signal)
        db.session.commit()
        
        # Mark as processed
        self.mark_as_processed(raw_signal.rss_item_id)
        
        # Rate limiting
        time.sleep(self.rate_limit_sleep_sec)
        
        return processed_signal

    def process_signals_batch(self, articles: List[Dict[str, Any]], batch_size: int = None) -> List[ProcessedSignal]:
        """
        Process a batch of signals, filtering out already processed ones.
        
        Args:
            articles: List of article dictionaries from EIOS
            batch_size: Maximum number of signals to process in this batch. If None, process all signals.
            
        Returns:
            List of processed signals
        """
        if batch_size is None:
            batch_size = len(articles)
        
        processed_signals = []
        processed_count = 0
        
        for article in articles:
            if processed_count >= batch_size:
                break
                
            rss_item_id = str(article.get('id', ''))
            
            # Skip if already processed
            if self.is_already_processed(rss_item_id):
                logger.info(f"Skipping already processed signal: {rss_item_id}")
                continue
            
            try:
                # Save raw signal
                raw_signal = self.save_raw_signal(article)
                
                # Get pinned status from article
                is_pinned = article.get('is_pinned', False)
                
                # Process signal
                processed_signal = self.process_signal(raw_signal, is_pinned)
                processed_signals.append(processed_signal)
                processed_count += 1
                
                logger.info(f"Processed signal {processed_count}/{batch_size}: {rss_item_id} (pinned: {is_pinned})")
                
            except Exception as e:
                logger.error(f"Error processing signal {rss_item_id}: {e}")
                continue
        
        logger.info(f"Batch processing complete. Processed {len(processed_signals)} signals.")
        return processed_signals

