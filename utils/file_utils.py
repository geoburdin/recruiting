import os
import json
import logging
from datetime import datetime
from typing import List, Dict
from core.db import get_db_connection
from dotenv import load_dotenv

from schemas.candidate import CandidateScore
from core.config import settings
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
import requests
def send_candidates_to_api(final_output):
    candidates = final_output["candidates"]
    res_auth = requests.post(
        'https://gate.hrbase.info/auth/login',
        data={"email": os.getenv("EMAIL"), "password": os.getenv("PASSWORD")},
    )
    logger.info("Successfully logged in to HRBase API.")
    tkn = res_auth.content[16:-2].decode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {tkn}"
    }
    payload = {"candidates": candidates}
    response = requests.post(
        "https://gate.hrbase.info/imported-candidates/bulk-create",
        headers=headers,
        json=payload
    )
    logger.info(f"Candidates sent to the api")
def datetime_serializer(obj):
    """Custom JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def insert_candidates_to_db(vacancy_id: int, data: dict) -> None:             # ➋  NEW
    """
    Store selected candidates in `recruting_selected_candidates`.
    The whole payload is saved as a JSON string
    """
    conn_tunnel = get_db_connection()
    if not conn_tunnel:
        logger.error("Skipping DB insert – couldn't obtain database connection.")
        return

    conn, tunnel = conn_tunnel  # unpack connection and tunnel objects
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recruting_selected_candidates
                    (vacancy_id, date_time, data_json)
                VALUES (%s, %s, %s)
                """,
                (
                    vacancy_id,
                    datetime.utcnow(),
                    json.dumps(
                        data,
                        ensure_ascii=False,
                        default=datetime_serializer

                    ),
                ),
            )
        logger.info(
            "Saved %s candidates for vacancy %s to PostgreSQL.",
            len(data.get("candidates", [])),
            vacancy_id,
        )

        with conn.cursor() as cur_update:  # Use a new cursor for thread safety
            query_update = "UPDATE vacancies_vec SET need_to_be_processed = FALSE WHERE id = %s;"
            cur_update.execute(query_update, (vacancy_id,))
            conn.commit()
        print(f"Vacancy ID {vacancy_id} marked as processed in DB.")
    except Exception as exc:
        logger.error("Database insert failed: %s", exc)
    finally:
        # Always close the resources we opened
        try:
            conn.close()
        except Exception:
            pass
        try:
            tunnel.stop()
        except Exception:
            pass


def save_results_to_file(scores: List[CandidateScore],
                         vacancy_id: str | int | None = None,
                         filename_prefix="candidate_scores") -> str | None:
    """Formats results (already containing details) to the target structure, sorts, and saves to a local JSON file."""
    output_dir = settings.output_dir
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    if not scores:
        logger.warning("No scores provided to save.")
        return None

    # The input `scores` list now contains CandidateScore objects
    # that already have fullName, profileURL, and detailed data populated.

    # 1. Format the output
    output_candidates = []
    for score_item in scores:
        # Get details directly from the score_item
        profile_url = score_item.profileURL or "" # Use empty string if None
        full_name = score_item.fullName or "N/A" # Use N/A if None
        
        # Create base candidate info
        output_candidate = {
            "name": full_name,
            "sourceId": str(score_item.candidate_id),
            "sourceUrl": profile_url,
            "sourceType": "linkedin",
            "vacancyId": int(vacancy_id) if vacancy_id else 0,
            "info": {
                "score": score_item.score,
                "reasoning": score_item.reasoning or ""
            }
        }
        
        # Add detailed candidate data if available
        if hasattr(score_item, 'person_data'):
            output_candidate["info"]["details"] = {
                "person": score_item.person_data,
                "education": score_item.education_data if hasattr(score_item, 'education_data') else [],
                "positions": score_item.position_data if hasattr(score_item, 'position_data') else []
            }
        
        output_candidates.append(output_candidate)

    # 2. Sort the formatted candidates by score (descending)
    sorted_output_candidates = sorted(
        output_candidates, key=lambda x: x.get("info", {}).get("score", 0.0), reverse=True
    )

    # 3. Take only the top 50 candidates
    top_50_candidates = sorted_output_candidates[:50]
    logger.info(f"Saving top {len(top_50_candidates)} candidates to file.")

    # 4. Create the final dictionary with the top candidates
    final_output = {"candidates": top_50_candidates}
    final_output: dict = json.loads(json.dumps(final_output, default=datetime_serializer))

    # 5. Save to file
    try:
        """with open(filepath, 'w', encoding='utf-8') as f:
            # Use the custom serializer to handle datetime objects
            json.dump(final_output, f, indent=2, ensure_ascii=False, default=datetime_serializer)
            f.write("\n")
        logger.info(f"Formatted results saved to {filepath}")"""
        if int(vacancy_id) != 0:
            send_candidates_to_api(final_output)
        insert_candidates_to_db(int(vacancy_id) if vacancy_id else 0, final_output)

        return filepath
    except IOError as e:
        logger.error(f"Failed to save formatted results to file {filepath}: {e}")
        return None


def fetch_candidates_from_linkedin(vacancy_id:str, keywords: List[str], location: List[str], russian_speaking: bool = True):
    """
    Fetch candidates from LinkedIn using the provided keywords and location.
    This is a placeholder function and should be replaced with actual LinkedIn API calls.
    """
    # Placeholder for LinkedIn API call
    logger.info(f"Fetching candidates from LinkedIn with keywords: {keywords} and location: {location}")
    url = f"http://93.127.132.57:8911/get_ru_candidates" if russian_speaking else "http://93.127.132.57:8911/get_international_candidate"
    headers = {"Content-Type": "application/json"}
    payload = [
        {
            "vacancy_id": vacancy_id,
            "keywords": keywords,
            "start": "0",
            "geo": location
        }
    ]
    logger.info("Payload for LinkedIn API: %s", payload)
    params = {"querystring": json.dumps(payload)}
    response = requests.post(url, headers=headers, params=params)
    if response.status_code == 200:
        logger.info("Successfully fetched candidates from LinkedIn.")
    else:
        logger.error(f"Failed to fetch candidates from LinkedIn: {response.status_code} - {response.text}")



