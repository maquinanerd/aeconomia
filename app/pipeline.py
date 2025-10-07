import logging
import time
import random
import json
import re
from collections import OrderedDict
from urllib.parse import urlparse, urljoin
from typing import Dict, Any, Optional

from .config import (
    PIPELINE_ORDER,
    RSS_FEEDS,
    SCHEDULE_CONFIG,
    WORDPRESS_CONFIG,
    WORDPRESS_CATEGORIES,
    CATEGORY_ALIASES, # Import the new alias map
    PIPELINE_CONFIG,
)
from .store import Database
from .feeds import FeedReader
from .extractor import ContentExtractor
from .ai_processor import AIProcessor
from .categorizer import Categorizer
from .wordpress import WordPressClient
from .store import Database # Ensure Database is imported
from .html_utils import (
    merge_images_into_content,
    add_credit_to_figures,
    rewrite_img_srcs_with_wp,
    strip_credits_and_normalize_youtube,
    remove_broken_image_placeholders,
    strip_naked_internal_links,
)
from .ai_processor import AIProcessor
from .internal_linking import add_internal_links
from bs4 import BeautifulSoup
from .cleaners import clean_html_for_globo_esporte

logger = logging.getLogger(__name__)

CLEANER_FUNCTIONS = {
    'globo.com': clean_html_for_globo_esporte,
}

def _get_article_url(article_data: Dict[str, Any]) -> Optional[str]:
    """
    Extracts a valid URL from article data, prioritizing 'url', then 'link', then 'id' (guid).
    """
    url = article_data.get("url") or article_data.get("link") or article_data.get("id")
    if not url:
        return None
    try:
        p = urlparse(url)
        if p.scheme in ("http", "https"):
            return url
    except Exception:
        return None
    return None

BAD_HOSTS = {"sb.scorecardresearch.com", "securepubads.g.doubleclick.net"}
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

def is_valid_upload_candidate(url: str) -> bool:
    """
    Validates if a URL is a good candidate for uploading.
    Filters out trackers, avatars, and tiny images.
    """
    if not url:
        return False
    try:
        lower_url = url.lower()
        p = urlparse(lower_url)
        
        if not p.scheme.startswith("http"):
            return False
        if p.netloc in BAD_HOSTS:
            return False
        if not p.path.endswith(IMG_EXTS):
            return False
        
        # descarta imagens de avatar/author
        if "author" in lower_url or "avatar" in lower_url:
            return False
            
        # descarta imagens minúsculas (largura/altura <= 100 no querystring)
        dims = re.findall(r'[?&](?:w|width|h|height)=(\d+)', lower_url)
        if any(int(d) <= 100 for d in dims):
            return False
            
        return True
    except Exception:
        return False


def run_pipeline_cycle():
    """Executes a full cycle of the content processing pipeline."""
    logger.info("Starting new pipeline cycle.")

    # Load the internal link map once per cycle
    link_map = {}
    try:
        with open('data/internal_links.json', 'r', encoding='utf-8') as f:
            link_map = json.load(f)
        if link_map:
            logger.info(f"Successfully loaded internal link map with {len(link_map)} terms.")
    except FileNotFoundError:
        logger.warning("Internal link map 'data/internal_links.json' not found. Skipping internal linking.")
    except json.JSONDecodeError:
        logger.error("Error decoding 'data/internal_links.json'. Skipping internal linking.")

    db = Database()
    feed_reader = FeedReader(user_agent=PIPELINE_CONFIG.get('publisher_name', 'Bot'))
    extractor = ContentExtractor()
    wp_client = WordPressClient(config=WORDPRESS_CONFIG, categories_map=WORDPRESS_CATEGORIES)
    ai_processor = AIProcessor()

    processed_articles_in_cycle = 0

    try:
        for i, source_id in enumerate(PIPELINE_ORDER):
            # Check circuit breaker before processing
            consecutive_failures = db.get_consecutive_failures(source_id)
            if consecutive_failures >= 3:
                logger.warning(f"Circuit open for feed {source_id} ({consecutive_failures} fails) → skipping this round.")
                # Reset for the next cycle as per prompt "zere o contador na próxima"
                db.reset_consecutive_failures(source_id)
                continue

            feed_config = RSS_FEEDS.get(source_id)
            if not feed_config:
                logger.warning(f"No configuration found for feed source: {source_id}")
                continue

            category = feed_config['category']
            logger.info(f"Processing feed: {source_id} (Category: {category})")

            try:
                feed_items = feed_reader.read_feeds(feed_config, source_id)
                new_articles = db.filter_new_articles(source_id, feed_items)

                if not new_articles:
                    logger.info(f"No new articles found for {source_id}.")
                    continue

                logger.info(f"Found {len(new_articles)} new articles for {source_id}")

                for article_data in new_articles[:SCHEDULE_CONFIG.get('max_articles_per_feed', 3)]:
                    article_db_id = article_data['db_id']
                    try:
                        article_url_to_process = _get_article_url(article_data)
                        if not article_url_to_process:
                            logger.warning(f"Skipping article {article_data.get('id')} - missing/invalid URL.")
                            db.update_article_status(article_db_id, 'FAILED', reason="Missing/invalid URL")
                            continue

                        logger.info(f"Processing article: {article_data.get('title', 'N/A')} (DB ID: {article_db_id}) from {source_id}")
                        db.update_article_status(article_db_id, 'PROCESSING')
                        
                        html_content = extractor._fetch_html(article_url_to_process)
                        if not html_content:
                            db.update_article_status(article_db_id, 'FAILED', reason="Failed to fetch HTML")
                            continue

                        soup = BeautifulSoup(html_content, 'lxml')
                        domain = urlparse(article_url_to_process).netloc.lower()
                        
                        # Clean the soup based on the domain
                        for cleaner_domain, cleaner_func in CLEANER_FUNCTIONS.items():
                            if cleaner_domain in domain:
                                soup = cleaner_func(soup)
                                logger.info(f"Applied cleaner for {cleaner_domain}")
                                break

                        extracted_data = extractor.extract(str(soup), url=article_url_to_process)
                        if not extracted_data or not extracted_data.get('content'):
                            logger.warning(f"Failed to extract content from {article_data['url']}")
                            db.update_article_status(article_db_id, 'FAILED', reason="Extraction failed")
                            continue

                        main_text = extracted_data.get('content', '')
                        body_images_html = extracted_data.get('images', [])
                        content_for_ai = main_text + "\n".join(body_images_html)

                        # Step 2: Rewrite content with AI
                        rewritten_data, failure_reason = ai_processor.rewrite_content(
                            title=extracted_data.get('title'),
                            content_html=content_for_ai,
                            source_url=article_url_to_process,
                            category=category,
                            videos=extracted_data.get('videos', []),
                            images=extracted_data.get('images', []), # This is now a list of html tags, not urls
                            tags=[],  # Tags are generated by the AI in this flow
                            source_name=feed_config.get('source_name', ''),
                            domain=wp_client.get_domain(),
                            schema_original=extracted_data.get('schema_original')
                        )

                        if not rewritten_data:
                            reason = failure_reason or "AI processing failed"
                            # Check for the specific case where the key pool for the category is exhausted
                            if "pool is exhausted" in reason:
                                logger.warning(
                                    f"{feed_config['category']} pool exhausted → marking article FAILED → moving on."
                                )
                            else:
                                logger.warning(f"Article '{article_data.get('title', 'N/A')}' marked as FAILED (Reason: {reason}). Continuing to next article.")
                            db.update_article_status(article_db_id, 'FAILED', reason=reason)
                            continue

                        # Step 3: Validate AI output and prepare content
                        title = rewritten_data.get("titulo_final", "").strip()
                        content_html = rewritten_data.get("conteudo_final", "").strip()

                        if not title or not content_html:
                            logger.error(f"AI output for {article_url_to_process} missing required fields (titulo_final/conteudo_final).")
                            db.update_article_status(article_db_id, 'FAILED', reason="AI output missing required fields")
                            continue

                        # Step 3.1: HTML Processing and Cleanup
                        # Defensive cleanup of common AI errors (e.g., leftover placeholders)
                        content_html = remove_broken_image_placeholders(content_html)
                        content_html = strip_naked_internal_links(content_html)

                        # 3.2: Ensure images from original article exist in content, injecting if AI removed them
                        content_html = merge_images_into_content(
                            content_html,
                            extracted_data.get('images', [])
                        )
                        
                        # 3.3: Upload ONLY the featured image if it's valid
                        urls_to_upload = []
                        featured_image_url = extracted_data.get('featured_image_url')
                        if featured_image_url and is_valid_upload_candidate(featured_image_url):
                            urls_to_upload.append(featured_image_url)
                            logger.info(f"Valid featured image found, preparing for upload: {featured_image_url}")
                        else:
                            logger.info("No valid featured image to upload. The post will not have a highlight.")

                        uploaded_src_map = {}
                        uploaded_id_map = {}
                        logger.info(f"Attempting to upload {len(urls_to_upload)} image(s).")
                        for url in urls_to_upload:
                            media = wp_client.upload_media_from_url(url, title)
                            if media and media.get("source_url") and media.get("id"):
                                # Normalize URL to handle potential trailing slashes as keys
                                k = url.rstrip('/')
                                uploaded_src_map[k] = media["source_url"]
                                uploaded_id_map[k] = media["id"]
                        
                        # 3.4: Rewrite image `src` to point to WordPress
                        content_html = rewrite_img_srcs_with_wp(content_html, uploaded_src_map)

                        # 3.5: Add credits to figures (currently disabled)
                        # content_html = add_credit_to_figures(content_html, extracted_data['source_url'])

                        # Só player do YouTube (oEmbed) e sem “Crédito: …”
                        content_html = strip_credits_and_normalize_youtube(content_html)
                        
                        # Add credit line at the end of the post
                        source_name = RSS_FEEDS.get(source_id, {}).get('source_name', urlparse(article_url_to_process).netloc)
                        credit_line = f'<p><strong>Fonte:</strong> <a href="{article_url_to_process}" target="_blank" rel="noopener noreferrer">{source_name}</a></p>'
                        content_html += f"\n{credit_line}"

                        # Step 5: Prepare payload for WordPress

                        # 5.1: Combine fixed and AI-suggested categories
                        FIXED_CATEGORY_IDS = {8, 267} # Futebol, Notícias
                        
                        final_category_ids = set(FIXED_CATEGORY_IDS)

                        # Get category from feed config (the main one)
                        main_category_id = WORDPRESS_CATEGORIES.get(category)
                        if main_category_id:
                            final_category_ids.add(main_category_id)

                        # Get AI suggested categories
                        suggested_categories = rewritten_data.get('categorias', [])
                        if suggested_categories and isinstance(suggested_categories, list):
                            # Expects a list of dicts like [{'nome': 'Barcelona'}, {'nome': 'Champions League'}]
                            suggested_names = [cat['nome'] for cat in suggested_categories if isinstance(cat, dict) and 'nome' in cat]
                            
                            # Normalize category names using aliases
                            normalized_names = []
                            for name in suggested_names:
                                canonical_name = CATEGORY_ALIASES.get(name.lower(), name)
                                normalized_names.append(canonical_name)
                            
                            if suggested_names != normalized_names:
                                logger.info(f"Normalized category names: {suggested_names} -> {normalized_names}")

                            if normalized_names:
                                logger.info(f"Resolving AI-suggested category names: {normalized_names}")
                                dynamic_category_ids = wp_client.resolve_category_names_to_ids(normalized_names)
                                if dynamic_category_ids:
                                    final_category_ids.update(dynamic_category_ids)

                        # Step 4: Add internal links (now in the correct place)
                        if link_map:
                            logger.info("Attempting to add internal links with prioritization...")
                            content_html = add_internal_links(
                                html_content=content_html,
                                link_map_data=link_map,
                                current_post_categories=list(final_category_ids)
                            )

                        # 5.2: Determine featured media ID to avoid re-upload
                        featured_media_id = None
                        if featured_url := extracted_data.get('featured_image_url'):
                            k = featured_url.rstrip('/')
                            featured_media_id = uploaded_id_map.get(k)
                        else:
                            logger.info("No suitable featured image found after filtering; proceeding without one.")
                        if not featured_media_id and uploaded_id_map:
                            featured_media_id = next(iter(uploaded_id_map.values()), None)

                        # 5.3: Set alt text for uploaded images
                        focus_kw = rewritten_data.get("focus_keyphrase", "")
                        # The AI is asked to provide a dict like: { "filename.jpg": "alt text" }
                        alt_map = rewritten_data.get("image_alt_texts", {})

                        if uploaded_id_map and (alt_map or focus_kw):
                            logger.info("Setting alt text for uploaded images.")
                            for original_url, media_id in uploaded_id_map.items():
                                # Extract filename from the original URL to match keys in alt_map
                                filename = urlparse(original_url).path.split('/')[-1]

                                # Try to get specific alt text from AI, fallback to a generic one
                                alt_text = alt_map.get(filename)
                                if not alt_text and focus_kw:
                                    alt_text = f"{focus_kw} — foto ilustrativa"

                                if alt_text:
                                    wp_client.set_media_alt_text(media_id, alt_text)

                        # 5.4: Prepare Yoast meta, including canonical URL to original source
                        yoast_meta = rewritten_data.get('yoast_meta', {})
                        yoast_meta['_yoast_wpseo_canonical'] = article_url_to_process

                        # Add related keyphrases if present
                        related_kws = rewritten_data.get('related_keyphrases')
                        if isinstance(related_kws, list) and related_kws:
                            # Yoast stores this as a JSON string of objects: [{"keyword": "phrase"}, ...]
                            yoast_meta['_yoast_wpseo_keyphrases'] = json.dumps([{"keyword": kw} for kw in related_kws])

                        post_payload = {
                            'title': title,
                            'slug': rewritten_data.get('slug'),
                            'content': content_html,
                            'excerpt': rewritten_data.get('meta_description', ''),
                            'categories': list(final_category_ids),
                            'tags': rewritten_data.get('tags_sugeridas', []),
                            'featured_media': featured_media_id,
                            'meta': yoast_meta,
                        }

                        wp_post_id = wp_client.create_post(post_payload)

                        if wp_post_id:
                            db.save_processed_post(article_db_id, wp_post_id)
                            logger.info(f"Successfully published post {wp_post_id} for article DB ID {article_db_id}")
                            processed_articles_in_cycle += 1
                        else:
                            logger.error(f"Failed to publish post for {article_url_to_process}")
                            db.update_article_status(article_db_id, 'FAILED', reason="WordPress publishing failed")

                        # Per-article delay to respect API rate limits.
                        delay = 120
                        logger.info(f"Sleeping for {delay}s (per-article delay).")
                        time.sleep(delay)

                    except Exception as e:
                        logger.error(f"Error processing article {article_url_to_process or article_data.get('title', 'N/A')}: {e}", exc_info=True)
                        db.update_article_status(article_db_id, 'FAILED', reason=str(e))

                # If we reach here without a feed-level exception, the processing was successful
                db.reset_consecutive_failures(source_id)

            except Exception as e:
                logger.error(f"Error processing feed {source_id}: {e}", exc_info=True)
                db.increment_consecutive_failures(source_id)

            # Per-feed delay before processing the next source
            if i < len(PIPELINE_ORDER) - 1:
                next_feed = PIPELINE_ORDER[i + 1]
                delay = SCHEDULE_CONFIG.get('per_feed_delay_seconds', 15)
                logger.info(f"Finished feed '{source_id}'. Sleeping for {delay}s before next feed: {next_feed}")
                time.sleep(delay)

    finally:
        logger.info(f"Pipeline cycle completed. Processed {processed_articles_in_cycle} articles.")
        db.close()
        wp_client.close()
