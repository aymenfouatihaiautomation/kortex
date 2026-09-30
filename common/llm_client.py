"""Wrapper partagé autour du Claude Agent SDK pour les blocs 0 et 1.

Réutilise la session `claude login` déjà authentifiée sur cette machine (même
mécanisme que ai-sales-agent-employee) — pas de ANTHROPIC_API_KEY séparée
nécessaire pour la génération de texte. L'outil WebSearch (bloc 0) passe par
le même CLI Claude Code, pas par l'outil serveur payant de l'API Messages.
"""

import asyncio
import json
import os as _os
import re
import time

import anthropic
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

# --- Gemini Flash (optionnel, palier gratuit AI Studio) -------------------------------------------
#
# "gemini-2.5-flash" (demandé initialement) renvoie HTTP 404 sur ce compte : "This model
# models/gemini-2.5-flash is no longer available to new users. [...] use models/gemini-3.6-flash"
# (message d'erreur Google, constaté en direct) — remplacé en conséquence.
#
# Quota exact du palier gratuit NON vérifié ici (les paliers Gemini ont changé plusieurs fois) —
# `call_gemini_api` logge quand même le coût comme 0$ dans le tracker : à surveiller côté console
# Google si ce chemin devient un usage réel/répété, pas juste ponctuel.
GOOGLE_API_KEY = _os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class LLMCallError(RuntimeError):
    """Levée quand l'appel au Claude Agent SDK ne produit aucun texte exploitable."""


async def _run_query(
    prompt: str,
    allowed_tools: list[str] | None,
    system_prompt: str | None,
    max_turns: int,
) -> str:
    options = ClaudeAgentOptions(
        allowed_tools=allowed_tools or [],
        permission_mode="bypassPermissions",
        system_prompt=system_prompt,
        max_turns=max_turns,
    )

    text_parts: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)

    return "\n".join(text_parts).strip()


def run_prompt(
    prompt: str,
    allowed_tools: list[str] | None = None,
    system_prompt: str | None = None,
    max_turns: int = 6,
    max_retries: int = 4,
    retry_delay_seconds: float = 5.0,
) -> str:
    """Envoie un prompt au Claude Agent SDK et retourne le texte concaténé de la réponse.

    Retente jusqu'à `max_retries` fois sur une exception levée par le SDK/CLI sous-jacent (bug réel
    rencontré lors d'un run réel prolongé du Bloc 3.5 sur un 2ème cours : "Claude Code returned an
    error result: success", un hoquet de la couche subprocess, pas une erreur liée au contenu du
    prompt — reproduit plusieurs fois, y compris 3 échecs consécutifs SANS délai entre essais, d'où
    l'ajout d'un court délai : un hoquet ponctuel a plus de chances de se résorber en laissant
    quelques secondes plutôt qu'en ré-appelant immédiatement). N'avale jamais l'erreur : chaque
    nouvel essai est signalé explicitement, et l'exception d'origine est relevée si toutes les
    tentatives échouent."""
    text = ""
    for attempt in range(max_retries + 1):
        try:
            text = asyncio.run(_run_query(prompt, allowed_tools, system_prompt, max_turns))
            break
        except Exception:
            if attempt >= max_retries:
                raise
            print(
                f"[llm_client] Erreur transitoire du SDK (tentative {attempt + 1}/{max_retries + 1}), "
                f"nouvel essai dans {retry_delay_seconds:.0f}s..."
            )
            time.sleep(retry_delay_seconds)

    if not text:
        raise LLMCallError("Aucune réponse texte reçue du Claude Agent SDK.")
    return text


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Extrait et parse le premier bloc JSON d'une réponse LLM (avec ou sans ```json). Robuste aux
    caractères de contrôle non échappés, aux newlines/tabs littéraux ET aux guillemets internes non
    échappés à l'intérieur des valeurs string (cas fréquents avec Claude sur des réponses longues) —
    même correctif que marketing/config.py::extract_json, appliqué ici après deux échecs réels en
    production (pipeline/domain_agent.py::search_domain_trends, puis
    bloc1_curriculum_planning::plan_curriculum — deux classes de malformation différentes)."""
    match = _JSON_FENCE_RE.search(text)
    candidate = match.group(1) if match else text

    if not match:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise LLMCallError(f"Aucun objet JSON trouvé dans la réponse : {text[:200]!r}")
        candidate = candidate[start : end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Retire les caractères de contrôle non autorisés dans JSON (U+0000-U+001F sauf \t \n \r,
    # légaux en JSON string).
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", candidate)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Échappe les newlines/tabs littéraux à l'intérieur des strings JSON (cas fréquent : Claude met
    # un \n littéral dans une valeur JSON au lieu de \\n).
    def _escape_unescaped_control(s: str) -> str:
        result = []
        in_string = False
        escape_next = False
        for ch in s:
            if escape_next:
                result.append(ch)
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                result.append(ch)
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch in ("\n", "\r", "\t"):
                result.append(repr(ch)[1:-1])  # '\n' → '\\n'
                continue
            result.append(ch)
        return "".join(result)

    control_escaped = _escape_unescaped_control(cleaned)
    try:
        return json.loads(control_escaped)
    except json.JSONDecodeError:
        pass

    # Dernier recours : échappe les guillemets internes non échappés à l'intérieur des strings
    # (ex. un titre citant un terme entre guillemets sans backslash — casse le parsing avec
    # "Expecting ',' delimiter" bien plus loin dans le document, constaté en production sur
    # bloc1_curriculum_planning::plan_curriculum). Heuristique : un `"` rencontré alors qu'on est
    # déjà "dans une chaîne" n'est traité comme fermant que si le prochain caractère non-espace est
    # un délimiteur JSON valide (`,` `}` `]` `:`) ou la fin du texte — sinon c'est un guillemet
    # interne mal échappé par le LLM, qu'on échappe au lieu de le laisser rompre la structure.
    def _escape_unescaped_quotes(s: str) -> str:
        result = []
        in_string = False
        escape_next = False
        n = len(s)
        i = 0
        while i < n:
            ch = s[i]
            if escape_next:
                result.append(ch)
                escape_next = False
                i += 1
                continue
            if ch == "\\":
                escape_next = True
                result.append(ch)
                i += 1
                continue
            if ch == '"':
                if not in_string:
                    in_string = True
                    result.append(ch)
                else:
                    j = i + 1
                    while j < n and s[j] in " \t\r\n":
                        j += 1
                    if j >= n or s[j] in ",}]:":
                        in_string = False
                        result.append(ch)
                    else:
                        result.append('\\"')
                i += 1
                continue
            result.append(ch)
            i += 1
        return "".join(result)

    try:
        return json.loads(_escape_unescaped_quotes(control_escaped))
    except json.JSONDecodeError as exc:
        raise LLMCallError(f"JSON invalide après nettoyage : {exc} — extrait : {cleaned[:300]!r}") from exc


# --- Appel direct à l'API Anthropic (ANTHROPIC_API_KEY), avec suivi de coût -----------------------
#
# Ajouté 2026-08-07 : bascule des blocs de génération (0, 1, 2, 3.5, pricing) du CLI Claude Code
# (run_prompt ci-dessus, limité par le quota mensuel de l'abonnement) vers l'API Anthropic directe,
# facturée au token. `bloc3_video_production/slides.py` reste sur run_prompt tant qu'il n'a pas été
# explicitement inclus dans cette bascule. Un seul point d'appel ci-dessous, réutilisé par tous les
# blocs migrés — voir docs/LLM_API_MIGRATION.md pour le mapping bloc->modèle et l'estimation de coût.

# Tarifs approximatifs en $ / million de tokens — À VÉRIFIER sur https://anthropic.com/pricing avant
# de bâtir un budget dessus. Ce ne sont pas des tarifs facturés en temps réel, seulement une base pour
# l'estimation de coût affichée à chaque appel.
MODEL_PRICING_PER_MILLION_TOKENS = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Coût estimé (en $) d'un appel, à partir du nombre RÉEL de tokens renvoyé par l'API."""
    pricing = MODEL_PRICING_PER_MILLION_TOKENS.get(model)
    if pricing is None:
        return 0.0
    return (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]


class CostTracker:
    """Accumule le coût de plusieurs appels API au sein d'un même run (ex. tout un cours généré, ou
    une boucle de révision Bloc 3.5) et affiche un résumé lisible en fin de run."""

    def __init__(self, label: str = ""):
        self.label = label
        self.calls: list[dict] = []

    def record(self, model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self.calls.append(
            {"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost_usd}
        )

    @property
    def total_cost_usd(self) -> float:
        return sum(c["cost_usd"] for c in self.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c["input_tokens"] for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c["output_tokens"] for c in self.calls)

    def print_summary(self) -> None:
        # "~" plutôt que "≈" (voir call_chat_api ci-dessous) : ce résumé peut aussi s'imprimer sur
        # une console Windows cp1252 (ex. scripts hors-ligne lancés en local), où "≈" lève
        # UnicodeEncodeError.
        label = f" [{self.label}]" if self.label else ""
        print(
            f"[cost]{label} total : {len(self.calls)} appel(s) — "
            f"{self.total_input_tokens:,} tokens in / {self.total_output_tokens:,} tokens out — "
            f"~ ${self.total_cost_usd:.4f}"
        )


def call_gemini_api(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 8192,
    tracker: CostTracker | None = None,
) -> str:
    """Appelle Gemini 2.5 Flash via l'API Google (palier gratuit AI Studio — quota exact non
    vérifié, voir avertissement près de GOOGLE_API_KEY plus haut). Lève `LLMCallError` si
    `GOOGLE_API_KEY` absent ou l'appel échoue après 3 tentatives (backoff 1s/2s/4s)."""
    import urllib.request

    if not GOOGLE_API_KEY:
        raise LLMCallError("GOOGLE_API_KEY manquante dans .env")

    if system_prompt:
        text_content = f"[SYSTEM]\n{system_prompt}\n[/SYSTEM]\n\n{prompt}"
    else:
        text_content = prompt
    contents = [{"role": "user", "parts": [{"text": text_content}]}]

    payload = json.dumps({
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7},
    }).encode("utf-8")

    url = f"{GEMINI_API_URL}?key={GOOGLE_API_KEY}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            if tracker is not None:
                # CostTracker n'a pas de méthode add() — la vraie méthode est record(model,
                # input_tokens, output_tokens, cost_usd), voir la classe plus haut.
                tracker.record(GEMINI_MODEL, 0, 0, 0.0)
            print(f"[cost] model={GEMINI_MODEL} in=0 out=0 (gratuit, palier AI Studio) ~ $0.0000")
            return text
        except Exception as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)

    raise LLMCallError(f"Gemini API échoué après 3 tentatives : {last_exc}") from last_exc


def call_llm_api(
    prompt: str,
    model: str,
    system_prompt: str | None = None,
    max_tokens: int = 4096,
    tracker: CostTracker | None = None,
    use_gemini: bool = False,
    task: str = "",
) -> str:
    """Appelle l'API Anthropic directe (ANTHROPIC_API_KEY, client `anthropic.Anthropic()`) et retourne
    le texte de la réponse.

    `use_gemini=True` bascule vers `call_gemini_api` (Gemini, palier gratuit) SI `GOOGLE_API_KEY`
    est configurée — retombe silencieusement sur Anthropic sinon (jamais d'exception juste parce
    que la clé Gemini manque, le comportement par défaut reste inchangé pour tout appelant qui ne
    passe pas `use_gemini=True`).

    `task` (ex. "curriculum", "content", "quality_control", "exam_questions", "domain_search"),
    quand fourni, PREND LE PAS sur `model`/`use_gemini` : le modèle et le fournisseur sont résolus
    par `pipeline.cost_controller.choose_model(task)`, qui bascule automatiquement de Gemini vers
    Claude Haiku une fois le quota gratuit journalier de Gemini épuisé (voir cost_controller.py
    pour le vrai chiffre de quota, vérifié en conditions réelles). Chaque appel réussi est ensuite
    journalisé via `record_call(task, ...)` pour que ce suivi de quota reste exact.

    Logge systématiquement le coût de CET appel (tokens réels + $ estimé, cf.
    MODEL_PRICING_PER_MILLION_TOKENS). Si `tracker` est fourni, y accumule aussi ce coût pour un
    résumé de run complet (ex. Bloc 3.5 : plusieurs allers-retours révision/relecture par chapitre).

    Le SDK anthropic officiel retente déjà en interne les erreurs réseau/5xx transitoires (comportement
    par défaut du client) — pas besoin de ré-implémenter la boucle de retry de run_prompt ici."""
    resolved_model = model
    resolved_use_gemini = use_gemini

    if task:
        from pipeline.cost_controller import choose_model
        resolved_model, resolved_use_gemini = choose_model(task)

    if resolved_use_gemini and GOOGLE_API_KEY:
        text = call_gemini_api(prompt, system_prompt=system_prompt or "", max_tokens=max_tokens, tracker=tracker)
        if task:
            from pipeline.cost_controller import record_call
            record_call(task, GEMINI_MODEL)
        return text

    kwargs: dict = {
        "model": resolved_model,
        "max_tokens": max_tokens,
        # Bug réel rencontré au premier run de production (Bloc 3.5, 2026-08-07) : claude-sonnet-5
        # active la réflexion étendue par défaut dès que le prompt le "justifie" (ex. une revue
        # critique à 4 critères), et les tokens de réflexion sont prélevés sur `max_tokens` — sur un
        # budget pensé pour la seule réponse JSON, la réflexion a épuisé tout le budget et laissé un
        # texte de réponse VIDE (stop_reason="max_tokens", 0 token restant). Désactivée explicitement
        # : nos prompts demandent une sortie JSON structurée directe, pas un raisonnement exposé.
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(**kwargs)
    except Exception as exc:
        raise LLMCallError(f"Appel à l'API Anthropic échoué (modèle {resolved_model}) : {exc}") from exc

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = estimate_cost_usd(resolved_model, input_tokens, output_tokens)
    # "~" plutôt que "≈" (voir call_chat_api ci-dessous) : évite UnicodeEncodeError sur une console
    # Windows cp1252 (ex. scripts hors-ligne comme bloc7_exam_generation, lancés en local).
    print(f"[cost] model={resolved_model} in={input_tokens} out={output_tokens} ~ ${cost_usd:.4f}")
    if tracker is not None:
        tracker.record(resolved_model, input_tokens, output_tokens, cost_usd)

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise LLMCallError(f"Réponse vide de l'API Anthropic (modèle {resolved_model}).")
    if task:
        from pipeline.cost_controller import record_call
        record_call(task, resolved_model)
    return text


def call_chat_api(
    messages: list[dict],
    model: str,
    system_blocks: list[dict] | None = None,
    max_tokens: int = 1024,
    tools: list[dict] | None = None,
    tracker: CostTracker | None = None,
) -> str:
    """Appelle l'API Anthropic directe pour un tour de conversation multi-tours (chatbots).

    Séparée de `call_llm_api` (prompt unique, système en texte brut, pas d'outils) : les chatbots
    (Bloc 6 — général puis tuteur par cours) ont besoin d'un historique de messages, d'un système
    structuré en plusieurs blocs de contenu (pour placer `cache_control` sur la portion stable du
    prompt système, ex. les métadonnées du catalogue) et d'outils serveur optionnels (ex.
    `web_search`). Changer la signature de `call_llm_api` pour couvrir ce cas casserait tous ses
    appelants existants (blocs 0-3.5) ; cette fonction ajoute le cas sans y toucher.

    `system_blocks`, si fourni, est passé tel quel comme valeur du paramètre `system` — c'est
    l'appelant qui place `cache_control` sur le(s) bloc(s) qui doivent être mis en cache (voir
    docs/prompt caching : le point de cache doit couvrir la portion stable, pas le contenu qui
    varie à chaque appel)."""
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        # Même raison que dans call_llm_api ci-dessus : nos prompts de chat attendent une réponse
        # texte directe, pas un raisonnement exposé qui grignoterait le budget de max_tokens.
        "thinking": {"type": "disabled"},
        "messages": messages,
    }
    if system_blocks:
        kwargs["system"] = system_blocks
    if tools:
        kwargs["tools"] = tools

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(**kwargs)
    except Exception as exc:
        raise LLMCallError(f"Appel à l'API Anthropic échoué (modèle {model}) : {exc}") from exc

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    cache_written = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    cost_usd = estimate_cost_usd(model, input_tokens, output_tokens)
    # "~" plutôt que "≈" (utilisé par call_llm_api) : ce print s'exécute dans une route HTTP
    # servie en production, y compris sur le serveur de dev local Windows dont la console par
    # défaut est en cp1252 — un caractère non-ASCII dans un print() y lève UnicodeEncodeError et
    # fait planter la requête (bug réel constaté en testant cette route en local).
    print(
        f"[cost] model={model} in={input_tokens} out={output_tokens} "
        f"cache_read={cache_read} cache_write={cache_written} ~ ${cost_usd:.4f}"
    )
    if tracker is not None:
        tracker.record(model, input_tokens, output_tokens, cost_usd)

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise LLMCallError(f"Réponse vide de l'API Anthropic (modèle {model}).")
    return text
