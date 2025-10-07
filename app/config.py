import os
from dotenv import load_dotenv
from typing import Dict, List, Any

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()

# --- Ordem de processamento dos feeds ---
PIPELINE_ORDER: List[str] = [
    'valor_financas',
    'g1_economia',
    'folha_mercado',
    'estadao_economia',
    'infomoney_economia',
    'valor_politica',
    'g1_politica',
    'folha_poder',
    'estadao_politica',
    'infomoney_politica',
    'infomoney_mercados',
    'infomoney_onde_investir',
    'bloomberg_markets',
    'bloomberg_economics',
    'nytimes_business',
    'nytimes_economy',
]

# --- Feeds RSS (padronizados, sem "synthetic_from") ---
RSS_FEEDS: Dict[str, Dict[str, Any]] = {
    # Economia
    'valor_financas': {
        'urls': ['https://aprenderpoker.site/feeds/valor/financas/rss'],
        'category': 'economia',
        'source_name': 'Valor Econômico',
    },
    'g1_economia': {
        'urls': ['https://aprenderpoker.site/feeds/g1/economia/rss'],
        'category': 'economia',
        'source_name': 'G1',
    },
    'folha_mercado': {
        'urls': ['https://aprenderpoker.site/feeds/folha/economia/rss'],
        'category': 'economia',
        'source_name': 'Folha de S.Paulo',
    },
    'estadao_economia': {
        'urls': ['https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/economia/'],
        'category': 'economia',
        'source_name': 'Estadão',
    },
    'infomoney_economia': {
        'urls': ['https://www.infomoney.com.br/economia/feed/'],
        'category': 'economia',
        'source_name': 'InfoMoney',
    },
    # Política
    'valor_politica': {
        'urls': ['https://aprenderpoker.site/feeds/valor/politica/rss'],
        'category': 'politica',
        'source_name': 'Valor Econômico',
    },
    'g1_politica': {
        'urls': ['https://aprenderpoker.site/feeds/g1/politica/rss'],
        'category': 'politica',
        'source_name': 'G1',
    },
    'folha_poder': {
        'urls': ['https://aprenderpoker.site/feeds/folha/politica/rss'],
        'category': 'politica',
        'source_name': 'Folha de S.Paulo',
    },
    'estadao_politica': {
        'urls': ['https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/'],
        'category': 'politica',
        'source_name': 'Estadão',
    },
    'infomoney_politica': {
        'urls': ['https://www.infomoney.com.br/politica/feed/'],
        'category': 'politica',
        'source_name': 'InfoMoney',
    },
    # Mercados, Negócios e Investimentos
    'infomoney_mercados': {
        'urls': ['https://www.infomoney.com.br/mercados/feed/'],
        'category': 'mercados',
        'source_name': 'InfoMoney',
    },
    'infomoney_onde_investir': {
        'urls': ['https://www.infomoney.com.br/onde-investir/feed/'],
        'category': 'mercados',
        'source_name': 'InfoMoney',
    },
    # Bloomberg
    'bloomberg_markets': {
        'urls': ['https://aprenderpoker.site/feeds/bloomberg/markets/rss'],
        'category': 'internacional',
        'source_name': 'Bloomberg',
    },
    'bloomberg_economics': {
        'urls': ['https://aprenderpoker.site/feeds/bloomberg/economics/rss'],
        'category': 'internacional',
        'source_name': 'Bloomberg',
    },
    # The New York Times
    'nytimes_business': {
        'urls': ['https://rss.nytimes.com/services/xml/rss/nyt/Business.xml'],
        'category': 'internacional',
        'source_name': 'The New York Times',
    },
    'nytimes_economy': {
        'urls': ['https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml'],
        'category': 'internacional',
        'source_name': 'The New York Times',
    },
}

# --- HTTP ---
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/91.0.4472.124 Safari/537.36'
)

# --- Configuração da IA ---
def _load_ai_keys() -> List[str]:
    """
    Lê todas as chaves GEMINI_* do ambiente e as retorna em uma lista única e ordenada.
    """
    keys = {}
    for key, value in os.environ.items():
        if value and key.startswith('GEMINI_'):
            keys[key] = value
    
    # Sort by key name for predictable order (e.g., GEMINI_ECONOMIA_1, GEMINI_POLITICA_1)
    sorted_key_names = sorted(keys.keys())
    
    return [keys[k] for k in sorted_key_names]

AI_API_KEYS = _load_ai_keys()

# Caminho para o prompt universal na raiz do projeto
PROMPT_FILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..',
    'universal_prompt.txt'
)

AI_MODEL = os.getenv('AI_MODEL', 'gemini-2.5-flash-lite')

AI_GENERATION_CONFIG = {
    'temperature': 0.7,
    'top_p': 1.0,
    'max_output_tokens': 4096,
}

# --- WordPress ---
WORDPRESS_CONFIG = {
    'url': os.getenv('WORDPRESS_URL'),
    'user': os.getenv('WORDPRESS_USER'),
    'password': os.getenv('WORDPRESS_PASSWORD'),
}

# --- Posts Pilares para Linkagem Interna ---
# Adicione aqui as URLs completas dos seus posts mais importantes.
# A lógica de linkagem interna dará prioridade máxima a links que apontam para estes artigos.
PILAR_POSTS: List[str] = [
    # Ex: "https://seusite.com/guia-completo-de-futebol",
    # Ex: "https://seusite.com/historia-das-copas-do-mundo",
]

# IDs das categorias no WordPress (ajuste os IDs conforme o seu WP)
WORDPRESS_CATEGORIES: Dict[str, int] = {
    'Notícias': 1,
    'economia': 132,
    'empreendedorismo': 134,
    'financas': 133,
    'mercados': 136,
    'mundo': 137,
    'politica': 135,
}

# --- Sinônimos de Categorias ---
# Mapeia nomes alternativos (em minúsculas) para o slug canônico em WORDPRESS_CATEGORIES
CATEGORY_ALIASES: Dict[str, str] = {
    "liga ea sports": "la-liga",
}

# --- Agendador / Pipeline ---
SCHEDULE_CONFIG = {
    'check_interval_minutes': int(os.getenv('CHECK_INTERVAL_MINUTES', 15)),
    'max_articles_per_feed': int(os.getenv('MAX_ARTICLES_PER_FEED', 3)),
    'per_article_delay_seconds': int(os.getenv('PER_ARTICLE_DELAY_SECONDS', 8)),
    'per_feed_delay_seconds': int(os.getenv('PER_FEED_DELAY_SECONDS', 15)),
    'cleanup_after_hours': int(os.getenv('CLEANUP_AFTER_HOURS', 72)),
}

PIPELINE_CONFIG = {
    'images_mode': os.getenv('IMAGES_MODE', 'hotlink'),  # 'hotlink' ou 'download_upload'
    'attribution_policy': 'Fonte: {domain}',
    'publisher_name': 'VocMoney',
    'publisher_logo_url': os.getenv(
        'PUBLISHER_LOGO_URL',
        'https://exemplo.com/logo.png'  # TODO: atualizar para a URL real do logo
    ),
}
