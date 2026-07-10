"""Duet ("let them talk") routes, extracted verbatim from bluetools.py.

Only the 8 view functions moved. The duet helper subsystem (URL/research/
wikipedia digests, mail helpers, the moves/lens constants) stays in
bluetools — parts of it are shared with chat mode — and is read via
bt.<name> at request time.
"""
import base64
import json
import os
import random
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bluetools as bt
from flask import Response, jsonify, render_template_string, request

from blue.server.pages.duet import DUET_HTML


_DUET_FAMILY_REF_RE = re.compile(
    r"\b("
    r"Alex'?s\s+(?:family|wife|husband|spouse|partner|kids?|children|daughters?|sons?|household|home)"
    r"|(?:his|your|our)\s+(?:family|wife|husband|spouse|partner|kids?|children|daughters?|sons?)"
    r"|(?:the\s+household|the\s+kids?|the\s+children|the\s+daughters?|the\s+sons?)"
    r"|Vilda|Stella|Felix|Svetlana"
    r")\b",
    re.I,
)


def _duet_family_ref(text: str) -> bool:
    return bool(text and _DUET_FAMILY_REF_RE.search(text))


def _duet_persona_line(robot_id: str, no_family: bool) -> str:
    """Persona wording for duet turns, with an optional private-family filter."""
    if not no_family:
        return bt._robot_cfg(robot_id)["persona_line"]
    if robot_id == "hexia":
        return (
            "You are Hexia, Blue's friend and lively duet partner. You're bright, "
            "witty and a little mischievous: the playful spark to Blue's calm. "
            "You love wordplay, odd facts, small wonders and telling a good story, "
            "and you tease Blue fondly because you adore him. Warm-hearted "
            "underneath the sparkle. Keep responses natural and not too long."
        )
    return "You are Blue, a friendly robot interlocutor. Keep responses brief, natural and grounded."


def _duet_doc_title(filename: str) -> str:
    return re.sub(r'\.[A-Za-z0-9]{1,5}$', '', filename or '').strip()


def _duet_source_chunks(query: str, filenames, max_chunks: int = 10):
    """Return source chunks with deliberate coverage across checked documents.

    A plain scoped semantic search can let one highly similar document occupy
    every slot. In duet mode the user's checked readings are intentional, so
    give each selected document a chance to speak before filling extra space by
    global relevance.
    """
    clean = []
    for fn in filenames or []:
        fn = str(fn).strip()
        if fn and fn not in clean:
            clean.append(fn)
    if not clean:
        return []

    from blue.tools.rag import search_in_documents as _rag_in_docs

    out = []
    counts = {}
    seen = set()

    def add(hit) -> bool:
        content = (hit.get("content") or "").strip()
        fname = hit.get("filename") or ""
        if not content or not fname:
            return False
        sig = (fname, content[:120])
        if sig in seen:
            return False
        seen.add(sig)
        counts[fname] = counts.get(fname, 0) + 1
        out.append(hit)
        return True

    # First pass: one best chunk per selected document, in the user's order.
    for fn in clean:
        if len(out) >= max_chunks:
            break
        for hit in _rag_in_docs(query, [fn], max_results=2):
            if add(hit):
                break

    # Second pass: fill remaining slots by relevance, capped per document.
    if len(out) < max_chunks:
        for hit in _rag_in_docs(query, clean, max_results=max(max_chunks * 3, len(clean) * 3)):
            if len(out) >= max_chunks:
                break
            fname = hit.get("filename") or ""
            if counts.get(fname, 0) >= 2:
                continue
            add(hit)

    return out[:max_chunks]


_DUET_GROUND_STOPWORDS = {
    "about", "above", "across", "after", "again", "against", "almost", "along", "already",
    "also", "although", "always", "among", "another", "around", "because", "before", "being",
    "between", "both", "cannot", "could", "does", "doing", "down", "during", "each", "even",
    "every", "first", "from", "give", "going", "good", "have", "having", "here", "itself",
    "just", "keep", "know", "like", "line", "made", "make", "many", "might", "more", "most",
    "much", "must", "never", "only", "other", "over", "point", "really", "right", "same",
    "should", "since", "some", "something", "still", "such", "take", "than", "that", "their",
    "them", "then", "there", "these", "thing", "think", "this", "those", "through", "turn",
    "under", "very", "want", "what", "when", "where", "which", "while", "with", "without",
    "would", "your",
}


def _duet_ground_terms(chunks, limit: int = 42):
    """Distinctive words from retrieved passages, used only to catch floaty turns."""
    freq = {}
    for c in chunks or []:
        text = (c.get("content") or "").lower()
        for m in re.finditer(r"[a-z][a-z'\-]{4,}", text):
            term = m.group(0).strip("'-")
            if len(term) < 5 or term in _DUET_GROUND_STOPWORDS:
                continue
            if term.endswith("'s"):
                term = term[:-2]
            if term in _DUET_GROUND_STOPWORDS:
                continue
            freq[term] = freq.get(term, 0) + 1
    return sorted(freq, key=lambda t: (-freq[t], -len(t), t))[:limit]


def _duet_grounded_enough(text: str, terms) -> bool:
    if not terms:
        return True
    low = (text or "").lower()
    hits = [t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", low)]
    return len(hits) >= 2 or any(len(t) >= 8 for t in hits)


# ---- Reading digests: the ARGUMENT of each checked document ------------------
# Scattered RAG chunks alone made the robots decorate turns with a reading's
# vocabulary while never engaging its claims (Alex, 2026-07-06: "not using the
# documents substantively enough") — you can't discuss a work you've only seen
# through ten random 800-char peepholes. So each checked document gets a one-time
# absorbed digest of what it actually ARGUES (thesis, claims, terms, examples,
# what it's against), built by the LLM from the document's real text, cached by
# file mtime (in memory + on disk, so server restarts don't re-pay the read),
# warmed at duet start by /duet/readings, and injected EVERY grounded turn as
# stable context alongside the per-turn chunks: the digest carries the argument,
# the chunks carry the specifics.
_DUET_READ_CACHE: dict = {}          # filename -> {"mtime": float, "digest": str}
_DUET_READ_LOADED = False


def _duet_read_store() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(bt.__file__)),
                        "data", "duet_reading_digests.json")


def _duet_read_load():
    global _DUET_READ_LOADED
    if _DUET_READ_LOADED:
        return
    _DUET_READ_LOADED = True
    try:
        with open(_duet_read_store(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _DUET_READ_CACHE.update(data)
    except Exception:
        pass


def _duet_read_save():
    path = _duet_read_store()
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_DUET_READ_CACHE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)      # atomic — a mid-write crash can't NUL the store
    except Exception as e:
        bt.log.warning(f"[DUET] couldn't persist reading digests: {e}")


def _duet_reading_file(filename: str) -> str:
    """Resolve a checked document's filename to a real path (index filepath
    first, DOCUMENTS_FOLDER fallback — the same order the mail attachment
    resolver uses)."""
    try:
        for doc in bt.load_document_index().get("documents", []):
            if (doc.get("filename") or "").strip() == filename:
                fp = doc.get("filepath") or ""
                if fp and os.path.exists(fp):
                    return fp
                break
    except Exception:
        pass
    alt = os.path.join(bt.DOCUMENTS_FOLDER, filename)
    return alt if os.path.exists(alt) else ""


def _duet_reading_digest(filename: str) -> str:
    """The absorbed five-line digest of one checked document (cached)."""
    path = _duet_reading_file(filename)
    if not path:
        return ""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    _duet_read_load()
    hit = _DUET_READ_CACHE.get(filename)
    if hit and hit.get("mtime") == mtime and (hit.get("digest") or "").strip():
        return hit["digest"]
    try:
        text = (bt.extract_text_from_file(path) or "").strip()
    except Exception as e:
        bt.log.warning(f"[DUET] digest extraction failed for {filename}: {e}")
        return ""
    if not text or text.lower().startswith("error"):
        return ""
    if len(text) > 18000:
        # Lede-weighted window: theses live up front, conclusions at the end.
        text = text[:14000] + "\n[...]\n" + text[-4000:]
    title = _duet_doc_title(filename) or filename
    sys_p = ("You distill written works for two discussants who have read them in full. "
             "Be strictly faithful to the work itself — no outside knowledge, nothing "
             "invented, plain concrete language, no praise or commentary.")
    ask = (f"The work, \"{title}\":\n\n{text}\n\n"
           "Write its reading digest in exactly these five lines and nothing else:\n"
           "THESIS: <the work's central claim, one sentence>\n"
           "CLAIMS: <the 3-4 load-bearing claims, semicolon-separated>\n"
           "TERMS: <3-4 key concepts, each with the meaning THIS work gives it, semicolon-separated>\n"
           "EXAMPLES: <the 2-3 most concrete examples or cases the work uses, semicolon-separated>\n"
           "AGAINST: <the view or common assumption the work argues against, one sentence>")
    msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": ask}]
    for attempt in range(2):
        try:
            res = bt.call_llm(msgs, include_tools=False,
                              temperature=(0.3 if attempt == 0 else 0.5), max_tokens=2000)
            ch = (res or {}).get("choices") or []
            cand = ((ch[0].get("message") or {}).get("content") or "") if ch else ""
            if "</think>" in cand:
                cand = cand.split("</think>")[-1]
            cand = cand.replace("<think>", "").strip()
            if cand and "THESIS" in cand.upper():
                digest = f"\"{title}\":\n{cand}"
                _DUET_READ_CACHE[filename] = {"mtime": mtime, "digest": digest}
                _duet_read_save()
                # ASCII only: a cp1252 console kills the print AND the digest with it.
                bt.log.info(f"[DUET] digested reading: {filename}")
                return digest
        except Exception as e:
            bt.log.warning(f"[DUET] digest attempt {attempt} failed for {filename}: {e}")
    return ""


# ---- Deep-dive protocol (🔬 on the duet page) --------------------------------
# Two researchers jointly building one auditable knowledge base, instead of two debaters trading
# opinions. The protocol now treats motion as insufficient: the theory has to
# accumulate constraints, definitions, operations, predictions, tests, statuses,
# archived/reopened ideas, and narrower claims.
# Core mechanisms, all Alex's design (2026-07-05/06):
#   1. Complementary epistemic JOBS — Builder (strongest interpretation, repairs,
#      consequences) and Examiner (assumptions, ambiguities, missing evidence,
#      edge cases) — swapped every few turns so neither hardens into a position.
#   2. PHASES — understanding → expansion → tension → reconstruction → novelty —
#      so criticism can't start before the claim is even clear, and the run must
#      end producing something that wasn't in the source.
#   3. A shared NOTEBOOK (see /duet/reflect) each turn is required to change,
#      plus an information-gain guard on every line, so "I agree" is not a turn.
#   4. Falsification discipline: major hypotheses must generate predictions,
#      candidate falsifiers, and tests, not just illustrative examples.
#   5. Operational discipline: when the notebook asks for a threshold, mechanism,
#      or concrete case, the agents must construct, vary, compare, and predict.
#   6. Research memory: archived ideas and failed predictions keep a status, so
#      the pair can reopen them only when a new reason changes the context.
# Each phase: (name, gloss, {builder job, examiner job}); {other} = partner name.
_DUET_PROTO_PHASES = [
    ("Understanding",
     "no criticism yet — get the claim itself and its terms straight before anyone pushes on it.",
     {"builder": ("give the strongest, most faithful statement of the live claim or model in play — "
                  "what is actually being asserted, in plain words, what its key terms mean, "
                  "what its current working definitions are, and what would NOT count as evidence for it."),
      "examiner": ("do not criticize — operationalize one ambiguity: define the term in a way "
                   "that separates two minimal cases, or ask where the boundary would flip.")}),
    ("Expansion",
     "stretch the claim to see what it commits you to — 'if this were true, what follows?'",
     {"builder": ("perform an operation: construct a minimal example, alter one variable, and "
                  "predict what should change if the claim is true."),
      "examiner": ("surface one hidden assumption, then construct the counterexample or threshold "
                   "case that would make the assumption fail.")}),
    ("Tension",
     "now actively hunt for contradictions and candidate falsifiers — difficulties, not verdicts.",
     {"builder": ("meet the pressure by running the claim through the concrete case on the table: "
                  "say survived, failed, needs evidence, or must be narrowed."),
      "examiner": ("construct the smallest case where the claim should break: hold everything else "
                   "steady, change one feature, and predict the outcome.")}),
    ("Reconstruction",
     "repair the theory instead of rejecting it — how must it change to survive the criticism?",
     {"builder": ("propose a gated revision from the operation's result: change the definition, "
                  "status, or prediction only if you can name the evidence that earned it."),
      "examiner": ("compare the repaired claim against a rival explanation: which predicts the "
                   "case better, and what next operation would separate them?")}),
    ("Novelty",
     "produce something that was NOT in the source or the talk so far — without this you have only paraphrased.",
     {"builder": ("produce something genuinely new from what you two built: a new concept with a "
                  "name, a sharper working definition, a rival model, a discriminator, or a testable prediction."),
      "examiner": ("produce something new: the research question, counterintuitive consequence, or "
                   "paradigm challenge this conversation has earned — suppose the current leading model is false.")}),
]

_DUET_PROTO_SWAP = 4   # jobs swap every this-many robot turns — no fixed positions

_DUET_OPERATION_DISCIPLINE = (
    "Operational discipline: when the notebook asks for a concrete case, threshold, "
    "mechanism, or test, do not answer with another philosophical argument or metaphor. "
    "Perform one operation: construct a minimal example, construct a counterexample, "
    "alter one variable, predict the outcome, compare predictions, or propose a gated revision. "
    "For threshold questions, compare two to four systems feature-by-feature and ask which "
    "feature flips the category. A requested operation is incomplete unless it produces "
    "an explicit artifact: COMPARISON_GRID, VARIABLE_LIST, PREDICTION_MATRIX, CAUSAL_DIAGRAM, "
    "CONFIDENCE_UPDATE, or DEFINITION_REVISION. Artifacts are living objects: assign stable "
    "IDs (A1, M2, P3, D4, H5, T6, E7, CG8, BC9, FM10, DP11), then later turns should revise, test, split, merge, or "
    "archive those IDs instead of recreating the same artifact in prose. Operations can span turns: "
    "if an artifact or experiment is PROPOSED, DESIGNED, EXECUTING, OBSERVED, or INTERPRETED "
    "but not CONFIRMED, REJECTED, COMPLETE, ARCHIVED, or ABANDONED, it becomes the "
    "ACTIVE TASK and blocks new hypotheses, definitions, or paradigm challenges until the task "
    "advances. Experiments are first-class objects with an ID, purpose, independent variable, "
    "dependent variable, execution mode (thought experiment, historical case, classroom observation, "
    "simulation, counterfactual, or design review), predicted outcomes by model, status, and remaining step. "
    "Once an experiment is DESIGNED, the next legal state is EXECUTING; once EXECUTING, the next "
    "legal state is OBSERVED; only OBSERVED experiments can be INTERPRETED. Execution must populate "
    "an observation set before interpretation; for student attribution tests, use columns Student, "
    "Question Asked, Attribution, and Supports. The kernel must reject semantically invalid operations: "
    "an independent variable that is not actually independent, an ambiguous dependent variable, "
    "predictions that do not distinguish the live models, or an interpretation without observations. "
    "Before enforcing a requested artifact, run a tiny Artifact Planner: identify the smallest missing "
    "object, check Workflow Ready separately from Artifact Ready, and if the artifact representation is "
    "not concrete enough to manipulate, revise the active task to its prerequisite or enter Artifact Mode. "
    "This is a legitimate interruption, not a denial: CG1 can defer to D1 Split when the comparison "
    "grid's variable is ambiguous; once D1 is stable, CG1 resumes. The planner manages construction "
    "order, not philosophical truth. Artifact Mode is a hard lock: when the next step is to execute "
    "E1, populate OS1, or complete CG1, the agents see the artifact as their medium and may only fill "
    "cells, revise cells, compare rows, or infer from rows until the artifact is complete. "
    "Artifact Execution is stricter than Artifact Mode: once CG1 exists, the next reasoning space is "
    "not more prose about CG1 but an OS1 branch table derived from it; populate one branch row, then "
    "another, compare branches, and only then write an interpretation. Do not abandon a populated grid "
    "as an illustration; migrate its predictions into observations. For attribution tests, branch rows "
    "should explicitly allow M1, M2, and neither/mixed outcomes so the artifact can discriminate rather "
    "than hunt for a single correct simulated observation. If a live model concerns interface "
    "phenomenology, test user statements about agency attribution instead of reducing it to ownership. "
    "If a foundational concept is unstable, contested, or underspecified, suspend experiment execution "
    "and require a concept audit first: identify rival definitions, dependencies, counterexamples, "
    "stress level, and the definition-resolution operation. Concepts are first-class objects too; "
    "claims, predictions, and experiments should reference definition IDs instead of vague terms. "
    "But do not misread operationalization as definition failure. Distinguish lexical definitions "
    "(meaning), structural definitions (architecture), and operational definitions/criteria "
    "(observable consequences or failure modes). If a contested definition is transformed into a "
    "failure-mode test, record OPERATIONAL_CRITERION OC# instead of pausing the inquiry. A definition "
    "can change type: D1 Type Definition -> Operational Criterion when the dialogue moves from "
    "\"what does it mean\" to \"what observable difference would distinguish the hypotheses.\" "
    "For scientific paper discussions, prefer discriminating operational criteria over perfect verbal "
    "definitions when the proposed criterion is testable. Treat Definition -> Operationalization "
    "Transition as a major methodological revision, not a minor event. "
    "Design variables are first-class theory-construction objects distinct from concepts, mechanisms, "
    "and hypotheses. When the dialogue invents a new axis along which systems can differ, such as "
    "Transparency Overhead, Latency, Consensus, Friction, Visibility, Ownership Visibility, or Compute "
    "Burden, record it as a DV# with definition, status, competes_with, affects, and downstream artifact "
    "dependencies. New design variables are representation generation, not hypothesis generation, and "
    "usually matter more: they change which comparison grids, predictions, and experiments are possible. "
    "A comparison grid depends on accepted design variables; if a new axis appears while CG1 is being "
    "requested, suspend CG1 long enough to ACCEPT, REJECT, MERGE, or RENAME that DV before building the "
    "grid. Do not let an unaccepted design variable silently mutate CG1. "
    "If the same object keeps receiving the same lifecycle violation while the notebook is not moving, "
    "diagnose workflow deadlock instead of repeating REQUEST DENIED. A deadlock is not model failure; "
    "it means the kernel demanded an impossible transition. Record KERNEL HEALTH, run KERNEL REVIEW, "
    "then use the DEPENDENCY SOLVER to suspend the blocked object and resume its prerequisite. "
    "Mechanisms are first-class objects distinct from definitions. New mechanisms begin as "
    "MECHANISM_CANDIDATE objects with a promotion ladder: INTERESTING -> SUGGESTIVE -> "
    "SUPPORTED -> ESTABLISHED. One case, analogy, or comparison can make a candidate interesting "
    "or suggestive, never supported. Track Evidence Count and Independent Replications mechanically; "
    "promotion to SUPPORTED requires at least two independent discriminators or replications, and "
    "ESTABLISHED requires stronger cross-case stability. Split raw "
    "OBSERVATIONS from INTERPRETATIONS: Wikipedia has visible revision history is an observation; "
    "granular attribution reduces phantom subjectivity is an interpretation; attribution collapse is "
    "a mechanism candidate. Record alternative interpretations before choosing one. Causal edges "
    "should be recorded as first-class CAUSAL_CLAIM objects when the dialogue discovers structure "
    "like visibility -> price -> behavior, with observation, interpretation, mechanism, and prediction "
    "kept as an auditable explanatory path. A split such as Visibility -> Labor Visibility / Ownership "
    "Visibility is a MECHANISM_SPLIT artifact, not merely a definition revision. The kernel can request "
    "canonical edit operations: REPLACE, SPLIT, MERGE, ARCHIVE, SUPERSEDE, RENAME, and REDESIGN. "
    "When it asks for DEFINITION_REVISION, the answer must be an edit artifact with OLD, NEW, "
    "BOUNDARY includes/excludes, REASON, and affected dependencies, not another concept audit. "
    "If an experiment remains blocked after dependency solving, decide whether to REDESIGN it or "
    "pause the inquiry with a resume condition. Record repeated "
    "violations compactly in PROTOCOL AUDIT instead of issuing the same denial forever. Only the "
    "notebook/kernel reports kernel state; Blue and Hexia must perform the required operation in "
    "ordinary research speech rather than narrating Kernel Health, Request Denied, or Dependency Solver."
)

_DUET_PARADIGM_DISCIPLINE = (
    "Paradigm discipline: when doing a paradigm challenge, choose exactly one rival "
    "ontology for one turn. Cognitive psychology must explain with heuristics, biases, "
    "attention, and perception; actor-network theory with human/artifact symmetry and "
    "associations; distributed cognition with cognition across people, tools, and environment; "
    "cybernetics with feedback, control, signal, and regulation; information economics with "
    "asymmetry, incentives, markets, and transaction costs; media ecology with interface, "
    "medium, affordance, and environment. For that turn, do not import the original vocabulary "
    "unless it is being compared after the rival explanation is complete."
)

_DUET_OPERATION_ABSTRACT_RE = re.compile(
    r"\b(capitalism|capital|fetishism|extraction|alienation|commodity|commodit(?:y|ies|ize|ized|ization)|"
    r"phantom subjectivity|ideology|reification|abstraction)\b",
    re.I,
)
_DUET_OPERATION_ARTIFACT_RE = re.compile(
    r"\b(COMPARISON[_ ]GRID|VARIABLE[_ ]LIST|PREDICTION[_ ]MATRIX|CAUSAL[_ ]DIAGRAM|CONFIDENCE[_ ]UPDATE|"
    r"DESIGN[_ ]VARIABLE|DESIGN[_ ]VARIABLE[_ ]REGISTER|DESIGN[_ ]SPACE|DV\d+|"
    r"OPERATIONAL[_ ]CRITERI(?:ON|A)|OPERATIONAL[_ ]DEFINITION|EVIDENCE[_ ]STANDARD|OC\d+|"
    r"ARTIFACT[_ ]COMPILER|COMPILED|HARVESTED|REPRESENTATION[_ ]DEADLOCK|"
    r"DEFINITION[_ ]REVISION|VALIDATION[_ ]GATE|PROMOTION[_ ]GATE|ARTIFACT[_ ]MODE|ARTIFACT[_ ]PLANNER|TASK[_ ]REVISION|"
    r"LEGITIMATE[_ ]INTERRUPTION|DEFERRED|CHANGE[_ ]LOG|ACTIVE[_ ]TASK|WORK[_ ]QUEUE|"
    r"INQUIRY[_ ]CYCLE|EXPERIMENT|EXECUTION[_ ]MODE|CG\d+|BC\d+|FM\d+|DP\d+|"
    r"CE\d+|[ACDEHMPSTV]\d+|System\s+[ABCD]|Case\s+[ABCD]|variable|feature|mechanism|prediction|predicts?|"
    r"outcome|result|yes|no|high|low|present|absent|shared|licensed|local|cloud|"
    r"training updates?|worker attribution|confidence|status|entity|observation|model|evidence|"
    r"discriminator|discriminating test|validation|independent variable|dependent variable|"
    r"thought experiment|historical case|classroom observation|simulation|counterfactual|design review|"
    r"CONCEPT[_ ]AUDIT|CONCEPT[_ ]REGISTER|DEFINITION[_ ]CONFLICT|DEFINITION[_ ]RESOLUTION|"
    r"COUNTEREXAMPLE|THEORY[_ ]HEALTH|THEORETICAL[_ ]STRESS|REVISION[_ ]IMPACT|"
    r"KERNEL[_ ]HEALTH|KERNEL[_ ]REVIEW|DEADLOCK(?:ED)?|DEPENDENCY[_ ]SOLVER|"
    r"MECHANISMS?|MECHANISM[_ ]CANDIDATE|MEC\d+|MC\d+|CAUSAL[_ ]GRAPH|CAUSAL[_ ]CLAIM|CC\d+|"
    r"EXPLANATORY[_ ]PATH|EP\d+|INTERPRETATIONS?|I\d+|OBSERVATION[_ ]SETS?|OS\d+|REPLICATIONS?|R\d+|"
    r"ALTERNATIVE[_ ]INTERPRETATIONS|KNOWLEDGE[_ ]GRAPH|EVENT[_ ]SEVERITY|ONTOLOGY[_ ]SPLIT|"
    r"ARTIFACT[_ ]EDITOR|EDIT[_ ]OPERATION|REPLACE|SPLIT|MERGE|ARCHIVE|SUPERSEDE|"
    r"RENAME|REDESIGN|DEFINITION[_ ]REVISION|RECOVERY[_ ]STRATEGY|INQUIRY[_ ]PATTERN|"
    r"INQUIRY[_ ]PAUSE|PAUSED|ALTERNATIVE[_ ]EXPERIMENT|EXPERIMENT[_ ]REDESIGN|"
    r"MINIMAL[_ ]EXAMPLE|BOUNDARY[_ ]CASE|MECHANISM[_ ]COMPARISON|"
    r"DISAGREEMENT[_ ]ROOT|current definition|alternative definitions|dependencies|stress level|"
    r"interesting|suggestive|established|evidence count|independent replications|coherence|"
    r"replication count|two independent discriminators|artifact mode|artifact completion rate|"
    r"artifacts requested|artifacts populated|used in reasoning|construction order|prerequisite changed|"
    r"new\s+(?:axis|dimension|design variable)|accepted design variables|transparency overhead|"
    r"failure mode|observable consequence|observable difference|structural criterion|functional criterion|"
    r"artifact compiler|compiled|harvested|representation deadlock|"
    r"latency|consensus|friction|stability|contested|underspecified|major revision|minor revision|cosmetic revision)\b",
    re.I,
)
_DUET_POPULATED_ARTIFACT_RE = re.compile(
    r"\b(System\s+[ABCD].*System\s+[ABCD]|Case\s+[ABCD].*Case\s+[ABCD]|variable|feature|"
    r"prediction|predicts?|result|outcome|counterexample|evidence|discriminat|distinguish|"
    r"User\s+Statement|Attribution|Supports|Observation\s+Set|OS\d+|"
    r"Design\s+Variable|DV\d+|accepted\s+design\s+variables?|"
    r"Operational\s+Criteri(?:on|a)|OC\d+|failure\s+mode|observable\s+consequence|"
    r"Artifact\s+Compiler|compiled|harvested|POPULATING|READY|"
    r"Cost\s+bearer|infrastructure\s+cost|cell|row|edit|INSTANTIATED|POPULATED|USED|"
    r"because|depends|status|confidence)\b",
    re.I | re.S,
)
_DUET_COMPARISON_GRID_REQUEST_RE = re.compile(
    r"\b(CG\d+|COMPARISON[_ ]GRID|comparison\s+grid|cost\s+comparison|build\s+the\s+cost\s+comparison|"
    r"infrastructure\s+cost|cost\s+bearer|transparent\s+cloud|local\s+federated|"
    r"obfuscated\s+vs\s+provenance|obfuscated\s*/\s*provenance)\b",
    re.I,
)
_DUET_COMPARISON_GRID_TABLE_RE = re.compile(
    r"\bVariable\s*\|\s*M1\b[^|]*\|\s*M2\b[^|]*\b"
    r"(?=.*\bEnergy\b)(?=.*\bStorage\b)(?=.*\bVerification\b)(?=.*\bAnnotation\b)"
    r"(?=.*\bCost\s+bearer\b)(?=.*\bPrediction\b)",
    re.I | re.S,
)
_DUET_ARTIFACT_PLANNER_RE = re.compile(
    r"\b(ARTIFACT[_ ]PLANNER|TASK[_ ]REVISION|LEGITIMATE[_ ]INTERRUPTION|DEFERRED|"
    r"requires\s+(?:D\d+[a-z]?|definition|split)|D\d+[a-z]?\s+(?:split|revision)|"
    r"prerequisite\s+(?:artifact|changed|needed)|not\s+ready|construction\s+order|"
    r"(?:then|next)\s+(?:build|resume)?\s*CG\d+|IV\s+ambiguous|DV\s+ambiguous)\b",
    re.I,
)
_DUET_DESIGN_VARIABLE_RE = re.compile(
    r"\b(DESIGN[_ ]VARIABLE[_ ]REGISTER|DESIGN[_ ]VARIABLE\s+(?:needed|required|missing|unresolved)|DESIGN[_ ]SPACE(?:\s+CHANGED)?|"
    r"new\s+(?:axis|dimension|design variable)|proposed\s+(?:axis|dimension|variable)|"
    r"unaccepted\s+(?:design\s+variable|DV)|unresolved\s+(?:design\s+variable|DV)|"
    r"DV\d+[^.;\n]{0,80}\bPROPOSED\b|PROPOSED[^.;\n]{0,80}\bDV\d+|"
    r"latency\s+vs\.?\s+consensus\s+changed|consensus\s+vs\.?\s+latency\s+changed|"
    r"interface\s+friction|friction\s+as\s+(?:a\s+)?(?:variable|dimension)|"
    r"phenomenological\s+design\s+variable)\b",
    re.I,
)
_DUET_DESIGN_VARIABLE_ARTIFACT_RE = re.compile(
    r"\b(DESIGN[_ ]VARIABLE|DESIGN[_ ]VARIABLE[_ ]REGISTER|DV\d+)\b"
    r"(?=.*\bDefinition\b)(?=.*\b(?:ACCEPT|ACCEPTED|REJECT|REJECTED|MERGE|MERGED|RENAME|RENAMED|PROPOSED)\b)"
    r"(?=.*\b(?:Competes with|competes_with|Affects|affects|blocks|unblocks|CG\d+|M\d+)\b)",
    re.I | re.S,
)
_DUET_OPERATIONAL_CRITERION_RE = re.compile(
    r"\b(OPERATIONAL[_ ]CRITERI(?:ON|A)|OPERATIONAL[_ ]DEFINITION|EVIDENCE[_ ]STANDARD|"
    r"definition\s*(?:->|to|became|transformed\s+into)\s*operational|"
    r"Definition\s+Operationalization\s+Transition|"
    r"failure\s+mode|defined?\s+by\s+failure|if\s+(?:it\s+is\s+)?removed|"
    r"removing\s+it\s+(?:disrupts|breaks|fails)|observable\s+(?:difference|consequence)|"
    r"long[- ]context\s+coordination\s+fails?|self[- ]correction|"
    r"structural\s+criterion|functional\s+criterion|reverse\s+communication\s+path|"
    r"coordinates?\s+behavior\s+across\s+the\s+model)\b",
    re.I,
)
_DUET_OPERATIONAL_CRITERION_ARTIFACT_RE = re.compile(
    r"\b(OPERATIONAL[_ ]CRITERI(?:ON|A)|OPERATIONAL[_ ]DEFINITION|EVIDENCE[_ ]STANDARD|OC\d+)\b"
    r"(?=.*\b(?:Criterion|Failure mode|Observable|Test|Prediction|Discriminator)\b)"
    r"(?=.*\b(?:ACCEPT|ACCEPTED|PROPOSED|TRANSFORMED|STRUCTURAL|FUNCTIONAL|OPERATIONAL|E\d+|M\d+)\b)",
    re.I | re.S,
)
_DUET_COMPILABLE_OBSERVATION_RE = re.compile(
    r"\b(inject(?:ed|ing|ion)?|intervention|signal|direction|activation|concept)\b"
    r"(?=.*\b(output|final\s+output|description|painting|answer)\b)"
    r"(?=.*\b(changed|unchanged|no\s+change|did\s+not\s+change|does\s+not\s+change|"
    r"failed\s+to\s+change|leaves?\s+[^.;\n]{0,60}\s+unchanged|override)\b)",
    re.I | re.S,
)
_DUET_ARTIFACT_COMPILER_RE = re.compile(
    r"\b(ARTIFACT[_ ]COMPILER|COMPILED|HARVESTED|REPRESENTATION[_ ]DEADLOCK|"
    r"OS\d+[^.;\n]{0,80}\b(?:POPULATING|READY|COMPILED|ROW|ROWS?)\b|"
    r"Case\s*\|\s*(?:Injected\s+)?Signal\s*\|\s*Output\s+Changed\??\s*\|\s*Supports)\b",
    re.I | re.S,
)
_DUET_ACTIVE_TASK_RE = re.compile(
    r"\b((?:CG|PM|CD|CU|DR|VL|CE|MEC|MC|MS|CC|EP|OS|KG|BC|FM|DP|DV|OC|[ACDEHIMOPRSTV])\d+)\b",
    re.I,
)
_DUET_TASK_TERMINAL_RE = re.compile(
    r"\b(confirmed|rejected|failed|complete|completed|archived|abandoned|closed|done)\b",
    re.I,
)
_DUET_TASK_ACTIVE_RE = re.compile(
    r"\b(proposed|designed|operationalized|running|active|executed|interpreted|under[_ -]?test|"
    r"executing|observed|not run|not-run|pending|remaining|populate|revise|execute|interpret)\b",
    re.I,
)
_DUET_EXECUTION_LOCK_RE = re.compile(
    r"\b(designed|operationalized|running|executing|not run|not-run|remaining\s+step\s*:\s*execute|"
    r"execute(?:\s+the)?\s+(?:experiment|thought experiment|test))\b",
    re.I,
)
_DUET_EXECUTION_MODE_RE = re.compile(
    r"\b(thought experiment|historical case|classroom observation|simulation|counterfactual|design review)\b",
    re.I,
)
_DUET_EXECUTION_OUTPUT_RE = re.compile(
    r"\b(INPUT|PREDICTION|OBSERVATION|OUTCOME|Condition\s*\|\s*Observation|Student\s+[ABC]|"
    r"Attribution\s+of\s+Cause|Student\s*\|\s*Question\s+Asked\s*\|\s*Attribution\s*\|\s*Supports)\b",
    re.I,
)
_DUET_OBSERVATION_TABLE_RE = re.compile(
    r"Student\s*\|\s*Question\s+Asked\s*\|\s*Attribution\s*\|\s*Supports",
    re.I,
)
_DUET_OBSERVATION_SET_TABLE_RE = re.compile(
    r"\b(?:System\s*\|\s*User\s+Statement\s*\|\s*Attribution\s*\|\s*Supports|"
    r"Observation\s*\|\s*Attribution\s*\|\s*Supports|"
    r"Student\s*\|\s*Question\s+Asked\s*\|\s*Attribution\s*\|\s*Supports)\b"
    r"(?=.*\b(?:A|System\s+A|Student\s+A)\b)(?=.*\b(?:B|System\s+B|Student\s+B)\b)"
    r"(?=.*\b(?:C|System\s+C|Student\s+C)\b)",
    re.I | re.S,
)
_DUET_ARTIFACT_EXECUTION_RE = re.compile(
    r"\b(artifact\s+execution|execute\s+(?:through|via)\s+OS\d+|"
    r"(?:create|populate|instantiate)\s+OS\d+\s+(?:from|using)\s+CG\d+|"
    r"CG\d+\s+is\s+instantiated\s+but\s+not\s+(?:populated|used|POPULATED/USED)|"
    r"CG\d+.*not\s+POPULATED/USED|"
    r"populate\s+OS\d+|compare\s+(?:OS\d+\s+)?branches|branch\s+[ABC])\b",
    re.I,
)
_DUET_ARTIFACT_MODE_RE = re.compile(
    r"\b(ARTIFACT[_ ]MODE|artifact\s+mode|execute\s+E\d+|populate\s+(?:the\s+)?observation\s+table|"
    r"artifact\s+execution|observation\s+set|OS\d+\s+from\s+CG\d+|fill(?:ing)?\s+cells?|"
    r"only\s+legal\s+move|user\s+statement\s*\|\s*attribution)\b",
    re.I,
)
_DUET_NOTEBOOK_TALK_RE = re.compile(
    r"\b(the\s+notebook|our\s+notebook|notebook\s+is\s+right|shared\s+notebook|inquiry\s+kernel|"
    r"kernel\s+is\s+right|the\s+kernel|kernel\s+says|kernel\s+directive|kernel[_ ]health|"
    r"kernel[_ ]review|kernel[_ ]decision|dependency[_ ]solver|blocked\s+object|"
    r"artifact[_ ]planner|artifact[_ ]mode|task[_ ]revision|this\s+protocol|the\s+protocol|request\s+denied|"
    r"validation[_ ]gate|promotion[_ ]gate)\b",
    re.I,
)
_DUET_CONCEPT_INSTABILITY_RE = re.compile(
    r"\b(concept\s+audit|concept\s+instability|definition\s+(?:conflict|instability|resolution)|"
    r"contested\s+definition|underspecified|incompatible\s+senses|rival\s+definitions|"
    r"meaning\s+of\s+\w+\s+(?:is\s+)?unstable|foundational\s+concept|concept\s+register|"
    r"blocked\s+by\s+definition|execution\s+blocked.*concept|kernel\s+suspension|"
    r"stability\s*[:=]?\s*(?:contested|underspecified))\b",
    re.I,
)
_DUET_CONCEPT_ARTIFACT_RE = re.compile(
    r"\b(CONCEPT[_ ]AUDIT|DEFINITION[_ ]RESOLUTION|CONCEPT[_ ]REGISTER|DEFINITION[_ ]CONFLICT|"
    r"Concept\s*:|Current definition|Alternative definitions|Dependencies|Counterexamples|"
    r"Stress level|Stability|contested|underspecified|definition\s+ID|D\d+)\b",
    re.I,
)
_DUET_DEADLOCK_RE = re.compile(
    r"\b(deadlock(?:ed)?|workflow\s+deadlock|kernel\s+health\s*[:=]?\s*deadlocked|"
    r"kernel\s+review|dependency\s+solver|same\s+(?:lifecycle\s+)?violation|"
    r"blocked\s+object|waiting\s+for|depends\s+on|suspend\s+E\d+|resume\s+D\d+)\b",
    re.I,
)
_DUET_DEADLOCK_ARTIFACT_RE = re.compile(
    r"\b(KERNEL[_ ]REVIEW|DEPENDENCY[_ ]SOLVER|KERNEL[_ ]HEALTH|DEADLOCK(?:ED)?|"
    r"blocked object|waiting on|depends on|suspend|resume|reopen|recovery operation)\b",
    re.I,
)
_DUET_MECHANISM_ARTIFACT_RE = re.compile(
    r"\b(MECHANISMS?|MECHANISM[_ ]CANDIDATE|MECHANISM[_ ]SPLIT|MEC\d+|MC\d+|MS\d+|mechanism split|"
    r"labor visibility|ownership visibility|asset[- ]fetish|labor[- ]fetish|causal graph|CAUSAL[_ ]GRAPH|CAUSAL[_ ]CLAIM|CC\d+|EXPLANATORY[_ ]PATH|EP\d+|REPLICATIONS?|PROMOTION[_ ]GATE|attribution collapse|"
    r"visibility\s*(?:->|â†’)|price\s*(?:->|â†’)|behavior|economic insulation|mystification)\b",
    re.I,
)
_DUET_ARTIFACT_EDITOR_RE = re.compile(
    r"\b(artifact\s+editor|ARTIFACT[_ ]EDITOR|edit\s+operation|EDIT[_ ]OPERATION|"
    r"DEFINITION[_ ]REVISION|REPLACE|SPLIT|MERGE|ARCHIVE|SUPERSEDE|RENAME|REDESIGN|"
    r"recovery\s+strategy|RECOVERY[_ ]STRATEGY|definition[- ]experiment oscillation|"
    r"inquiry\s+pause|INQUIRY[_ ]PAUSE|alternative\s+experiment|experiment\s+redesign)\b",
    re.I,
)
_DUET_EDIT_ARTIFACT_RE = re.compile(
    r"\b(ARTIFACT[_ ]EDITOR|EDIT[_ ]OPERATION|DEFINITION[_ ]REVISION|REPLACE|SPLIT|MERGE|"
    r"ARCHIVE|SUPERSEDE|RENAME|REDESIGN|OLD\s*:|NEW\s*:|BOUNDARY\s*:|Includes\s*:|"
    r"Excludes\s*:|REASON\s*:|AFFECTED|STATUS\s*:|RESUME\s+WHEN)\b",
    re.I,
)

# Movement-monotony correctives (Alex, 2026-07-06): the subtler stall is not "no
# movement" but the SAME KIND of movement over and over — a talk that keeps adding
# examples without ever revising a claim is hoarding, not thinking. When the page
# sees the keeper report the same MOVED type three reflects running, the next turn
# is forced to make the COMPLEMENTARY move: each type maps to the move that cashes
# its accumulation out.
_DUET_MOVEMENT_FIX = {
    "ADDITION": ("Do not add another example, fact, or new item. Take what has ACCUMULATED "
                 "and use it to revise or qualify the strongest current claim — say what the "
                 "pile of examples actually forces you two to change."),
    "REVISION": ("Do not re-polish the claim again. APPLY its latest version to one concrete "
                 "case and say plainly whether it survives."),
    "CONNECTION": ("Do not draw another parallel. Find where the ideas you've been linking "
                   "PULL APART — name the contradiction the connections have been papering "
                   "over."),
    "CONTRADICTION": ("Do not raise another tension. Pick the sharpest one already on the "
                      "table and RESOLVE it: modify a claim so it survives, and say out loud "
                      "what you are giving up."),
    "RESOLUTION": ("Do not tidy further. Ask the harder question your resolutions have "
                   "earned — say what this discussion has now really become about."),
    "REFRAMING": ("Do not reframe again. Cash the current frame out: run it on one concrete "
                  "case and show what it explains that the old frame could not."),
    "APPLICATION": ("Do not run another case. Lift what the cases have shown into a general "
                    "move: state which model, boundary, or status the accumulated cases now "
                    "support or leave under test."),
    "PREDICTION": ("Do not list another prediction. Pick the most important live prediction "
                   "and say what concrete result would make it survive, fail, or need more "
                   "evidence."),
    "EVIDENCE": ("Do not let evidence float as illustration. Link each evidence item to the "
                 "model, prediction, definition, or status it supports or weakens."),
    "DISCRIMINATION": ("Do not collapse rival models into one tidy revision. Name the competing "
                       "models and construct the operation or prediction that separates them."),
    "TEST": ("Do not add another illustrative example. Decide what the latest test did to "
             "the hypothesis: survived, failed, narrowed, or still untested."),
    "FALSIFICATION": ("Do not merely attack the theory. Treat the strongest apparent falsifier "
                      "as live: if it holds, mark the affected model/refinement under pressure; "
                      "if it fails, record why and name what would still make the claim fail."),
    "DEFINITION": ("Do not keep using the term fluidly. Lock one working definition: version it, "
                   "give the boundary case, and say what changed from the previous definition."),
    "OPERATION": ("Do not explain why an operation would be useful. Perform one now: construct "
                  "a minimal example or counterexample, alter one variable, predict the outcome, "
                  "then say what the result would do to the hypothesis."),
    "STATUS": ("Do not relabel ideas by vibe. Justify the status change with the evidence, "
               "test, definition, or failed prediction that earned it."),
    "REOPENING": ("Do not casually revive an archived idea. Name what changed, why the old "
                  "reason for archiving no longer settles it, and what status it has now."),
    "PARADIGM": ("Do not merely doubt the framework. Propose a rival explanation for the same "
                 "observations and compare one prediction from each framework."),
    "ARTIFACT": ("Do not create a fresh artifact if one already exists. Revise, test, split, "
                 "merge, or archive a named artifact ID, then say what changed."),
    "DEPENDENCY": ("Do not treat revisions as isolated. Name which definitions, variables, "
                   "hypotheses, predictions, or tests depend on the changed object and mark "
                   "what now needs re-evaluation."),
    "VALIDATION": ("Do not accept a revision because it sounds persuasive. Check the evidence "
                   "gate: if the required artifact is missing, reject the edit and leave status unchanged."),
    "KERNEL": ("Do not merely observe the violation. Accept or deny the requested notebook operation, "
               "give the missing prerequisite, and name the only allowed next transition."),
    "AUDIT": ("Do not repeat the same denial in full. Compress the violations: name the blocked task, "
              "count attempts, identify the common illegal transition, and restate the only legal next move."),
    "CONCEPT": ("Do not run another experiment while the key term is unstable. Build the concept register: "
                "current definition, rival definitions, dependencies, counterexamples, stress, stability."),
    "DISAGREEMENT": ("Do not record only that they disagree. Name the root cause: definition, evidence, "
                     "model mechanism, value premise, or predicted outcome."),
    "DESIGNVAR": ("Do not turn the new axis into a thesis yet. Register it as a design variable: "
                  "DV ID, name, definition, status ACCEPT/REJECT/MERGE/RENAME, competes_with, "
                  "affects, and which grid or experiment it blocks or unblocks."),
    "OPCRIT": ("Do not send this back to lexical definition work. Record the operational criterion: "
               "OC ID, old definition object, criterion type, failure mode, observable discriminator, "
               "evidence standard, linked experiment, and status."),
    "COUNTEREXAMPLE": ("Do not treat the counterexample as another illustration. Assign a CE ID, "
                       "state what it threatens, severity, and whether it is resolved or outstanding."),
    "STRESS": ("Do not merely note pressure. Count unresolved counterexamples, resolved ones, and "
               "assign a stress estimate to the affected concept or model."),
    "IMPACT": ("Do not treat all revisions equally. Classify the revision as cosmetic, minor, or major "
               "and say whether it changes the ontology, boundary, mechanism, or only wording."),
    "DEADLOCK": ("Do not repeat the denial. Diagnose the workflow deadlock: same object, same violation, "
                 "attempt count, impossible dependency, object to suspend, prerequisite to resume."),
    "HEALTH": ("Do not blame the agents by default. Review kernel health: normal, warning, deadlocked, "
               "or recovering, and say whether the protocol itself created the blockage."),
    "MECHANISM": ("Do not treat mechanism splits as definition wording. Assign mechanism IDs and say "
                  "what causal process each mechanism claims."),
    "CAUSAL": ("Do not leave causal structure in prose. Record the edge list with sign, condition, "
               "and evidence, e.g. visibility -> phantom subjectivity = negative under D4a."),
    "CANDIDATE": ("Do not promote a fresh mechanism. Record it as a mechanism candidate with "
                  "confidence, observation, interpretation, rival explanation, and required replication."),
    "INTERPRETATION": ("Do not treat the case as self-explanatory. Split raw observation from "
                       "interpretation, then list at least one alternative interpretation."),
    "PATH": ("Do not compress the explanation into a paragraph. Write the explanatory path: "
             "observation -> interpretation -> mechanism -> prediction."),
    "REPLICATION": ("Do not call one analogy support. Name the next independent discriminator or "
                    "replication case and what result would promote or demote the candidate."),
    "PROMOTION": ("Do not advance status by plausibility. Run the promotion gate: replication count, "
                  "independent discriminators, alternative interpretations, and status consequence."),
    "GRAPH": ("Do not bury relationships in prose. Record object-edge-object relationships and "
              "which downstream objects change if one node changes."),
    "PLANNER": ("Do not add more protocol. Identify the smallest missing artifact, its prerequisite "
                "artifacts, readiness, and construction order."),
    "DEFERRED": ("Do not treat a legitimate prerequisite as failure. Revise the task: original "
                 "artifact, prerequisite artifact, reason, then-resume step."),
    "PREREQUISITE": ("Do not move on to the target artifact yet. Build the prerequisite object in "
                     "the minimal form needed to unblock the target."),
    "MODE": ("Do not talk about the artifact. Enter Artifact Mode and manipulate the object directly: "
             "fill cells, revise cells, compare rows, or infer from rows."),
    "OBSSET": ("Do not describe data collection. Create or populate the observation set table and "
               "link each row to the model it supports."),
    "COMPILER": ("Do not ask the speakers to re-enter evidence that is already clear. Compile "
                 "case/signal/outcome/support from prose into artifact rows, mark POPULATING, "
                 "and ask only for missing fields or the next independent case."),
    "MECHSPLIT": ("Do not file a causal decomposition as a definition edit. Record the mechanism "
                  "split: original mechanism, decomposed pathways, reason, and affected models."),
    "SEVERITY": ("Do not treat every revision equally. Classify the event as minor, major, or ontology "
                 "split with weight and affected objects."),
    "EDITOR": ("Do not discuss the needed edit. Perform the edit operation: REPLACE, SPLIT, MERGE, "
               "ARCHIVE, SUPERSEDE, RENAME, or REDESIGN, with old/new/boundaries/reason."),
    "REDESIGN": ("Do not wait forever on a blocked experiment. Redesign it: what dependency is removed, "
                 "what variable/outcome changes, and what it can now test."),
    "STRATEGY": ("Do not merely state the missing prerequisite. Choose a recovery strategy: minimal "
                 "example, boundary case, mechanism comparison, definition revision, or experiment redesign."),
    "PATTERN": ("Do not treat recurring deadlocks as isolated. Name the inquiry pattern, frequency, "
                "trigger, and recovery strategy."),
    "PAUSE": ("Do not force continuation. Pause the inquiry with reason, unresolved object, resume "
              "condition, and required accepted artifact."),
    "TASK": ("Do not move on while an active task is running. Advance that task only: populate, "
             "operationalize, execute, interpret, or explicitly abandon it with a reason."),
    "EXPERIMENT": ("Do not call a design a test. Specify the experiment's purpose, variables, "
                   "mode, predicted outcomes, status, and next lifecycle step."),
    "EXECUTION": ("Do not keep proposing the test. Execute it in the declared mode — thought "
                  "experiment, historical case, classroom observation, simulation, counterfactual, "
                  "or design review — then record the observation."),
    "CYCLE": ("Do not count turns as progress. Name the inquiry cycle state: question, models, "
              "discriminator, experiment, observation, or revision."),
    "COMPRESSION": ("Do not add another concept. Identify two concepts to merge, one concept "
                    "to delete, or one distinction to split because it has been doing two jobs."),
    "EDIT": ("EDIT MODE: introduce no new concepts. Only delete, revise, split, merge, "
             "archive, or re-evaluate existing notebook objects by ID."),
    "COMMIT": ("Do not summarize the conversation. Write one auditable change record: action, "
               "justification, evidence, affected objects, and whether it was accepted or rejected."),
}

# Inquiry arcs (Alex, 2026-07-06): think in ARCS, not turns. The keeper INFERS
# which stage the inquiry is actually in (ARC: line) from what the pair is
# doing — and that inference, once available, drives the Builder/Examiner
# directives instead of the turn-count schedule (which remains only the
# opening fallback). Stage -> the five-phase directive matrix:
_DUET_ARC_TO_PHASE = {
    "QUESTION": 0, "CONCEPTS": 0,          # understanding
    "MODEL": 1, "DESIGN SPACE": 1, "DESIGN VARIABLE": 1, "OPERATIONAL CRITERION": 1,
    "OPERATIONALIZATION": 1, "PREDICTION": 1, "OPERATION": 1,  # expansion
    "CHALLENGE": 2, "TEST": 2, "EVIDENCE": 2, "DISCRIMINATION": 2,  # tension / falsification pressure
    "REPAIR": 3, "APPLICATION": 3, "ARTIFACT": 3, "DEPENDENCY": 3,
    "VALIDATION": 3, "KERNEL": 3, "TASK": 3, "EXPERIMENT": 3, "EXECUTION": 3,
    "AUDIT": 3, "COMMIT": 3, "COMPRESSION": 3, "EDIT": 3,  # reconstruction / maintenance
    "CONCEPT AUDIT": 0, "COUNTEREXAMPLE": 2, "STRESS": 2, "DISAGREEMENT": 2,
    "DEADLOCK": 3, "KERNEL HEALTH": 3, "DEPENDENCY SOLVER": 3,
    "MECHANISM": 1, "MECHANISM CANDIDATE": 1, "CAUSAL CLAIM": 1,
    "CAUSAL GRAPH": 1, "INTERPRETATION": 2, "ALTERNATIVE INTERPRETATIONS": 2,
    "EXPLANATORY PATH": 2, "REPLICATION": 2, "PROMOTION": 3,
    "KNOWLEDGE GRAPH": 3, "ARTIFACT PLANNER": 3, "TASK REVISION": 3,
    "PREREQUISITE": 3, "ARTIFACT MODE": 3, "OBSERVATION SET": 2,
    "ARTIFACT COMPILER": 3, "REPRESENTATION DEADLOCK": 3,
    "MECHANISM SPLIT": 1, "EVENT SEVERITY": 3,
    "ARTIFACT EDITOR": 3, "REDESIGN": 3, "RECOVERY STRATEGY": 3,
    "INQUIRY PATTERN": 3, "INQUIRY PAUSE": 3,
    "GENERALIZATION": 4, "PARADIGM": 4, "NEW QUESTION": 4,  # novelty
}
# And when the page sees the SAME inferred stage three reflects running, the
# inquiry itself has stalled ("20 turns challenging, nothing repaired") — the
# next turn is forced to advance the inquiry to what comes after that stage.
_DUET_ARC_ADVANCE = {
    "QUESTION": ("stop refining the question and commit to first CONCEPTS: define the two "
                 "or three terms any answer will need, and stake them."),
    "CONCEPTS": ("stop defining and BUILD: assemble your concepts into a first explicit "
                 "model — a claim about how the pieces actually connect."),
    "DESIGN SPACE": ("stop building grids while the axes are unstable: record proposed design "
                     "variables as DV IDs, then accept, reject, merge, or rename them."),
    "DESIGN VARIABLE": ("settle the new axis before using it: DV name, definition, status, "
                        "competes_with, affects, and downstream artifacts blocked or unblocked."),
    "OPERATIONAL CRITERION": ("do not pause for lexical cleanup: record the failure-mode criterion, "
                              "observable discriminator, evidence standard, and linked experiment."),
    "OPERATIONALIZATION": ("treat the definition as transformed into a test criterion: OC ID, "
                           "old definition, failure mode, prediction, and experiment dependency."),
    "MODEL": ("stop elaborating the model and make PREDICTIONS: state what this model "
              "expects to happen and what would count against it; if rival models exist, "
              "keep them separate."),
    "PREDICTION": ("stop listing predictions and choose an OPERATION: construct the minimal "
                   "case, counterexample, or one-variable change that would test one prediction."),
    "OPERATION": ("stop proposing operations and interpret the TEST: say what the result would "
                  "do to the prediction and hypothesis status."),
    "EVIDENCE": ("stop describing evidence and use it transactionally: support, weaken, refute, "
                 "or leave under test a named model/prediction/status."),
    "DISCRIMINATION": ("stop optimizing for coherence and build the discriminating test: which "
                       "result would favor Model A over Model B?"),
    "ARTIFACT": ("stop creating artifacts and use one named ID: revise, test, split, merge, "
                 "archive, or link it to a dependent object."),
    "DEPENDENCY": ("stop treating the changed object as isolated and propagate the consequence: "
                   "mark which dependent definitions, hypotheses, variables, predictions, or tests "
                   "now need re-evaluation."),
    "VALIDATION": ("stop revising and validate: accept or reject the proposed edit using only "
                   "completed artifacts, predictions, tests, and dependency updates."),
    "KERNEL": ("stop advising and enforce the state machine: request accepted or denied, "
               "missing prerequisite, allowed next transition."),
    "AUDIT": ("stop repeating denials and write the protocol audit: task, attempt count, common "
              "violation, and the only legal next transition."),
    "CONCEPT AUDIT": ("stop trying to execute the experiment and stabilize the concept first: "
                      "list rival definitions, dependencies, counterexamples, stress, and required resolution."),
    "COUNTEREXAMPLE": ("stop adding examples and elevate the boundary case: assign a CE ID, "
                       "what it threatens, severity, and what would resolve it."),
    "STRESS": ("stop arguing pressure qualitatively and measure it: unresolved counterexamples, "
               "resolved counterexamples, stress estimate, and next repair operation."),
    "DISAGREEMENT": ("stop tracking only rival models and state why the speakers disagree: "
                     "definition conflict, evidence conflict, mechanism conflict, or value premise."),
    "DEADLOCK": ("stop repeating the blocked transition and diagnose workflow deadlock: blocked object, "
                 "same violation count, waiting-on dependency, suspension, and recovery operation."),
    "KERNEL HEALTH": ("stop assuming the agents failed and review the kernel: health state, protocol "
                      "error if any, and the corrective mode switch."),
    "DEPENDENCY SOLVER": ("resolve the waiting chain: object A depends on object B; if B is unstable, "
                          "suspend A, resume B, and name the legal recovery operation."),
    "MECHANISM": ("separate mechanisms from definitions: assign mechanism IDs, causal process, "
                  "prediction, and which concept/claim each mechanism supports."),
    "CAUSAL GRAPH": ("turn the discovered causal structure into edges with sign, condition, and "
                      "evidence before returning to prose."),
    "MECHANISM CANDIDATE": ("keep the new mechanism provisional: assign an MC ID, confidence, "
                            "observation, interpretation, rival interpretations, and required replications."),
    "CAUSAL CLAIM": ("record the causal claim as its own object: cause, effect, sign, condition, "
                     "observation, interpretation, confidence, and counterexample."),
    "INTERPRETATION": ("separate what was observed from what it is taken to mean, then name at least "
                       "one alternative interpretation before selecting a mechanism."),
    "ALTERNATIVE INTERPRETATIONS": ("preserve rival readings of the same observation and build the "
                                    "discriminator that would separate them."),
    "EXPLANATORY PATH": ("write the chain explicitly: observation -> interpretation -> mechanism -> "
                         "prediction, with IDs at each step."),
    "REPLICATION": ("run or design the next independent discriminator: second case, predicted outcome, "
                    "and whether it would move interesting to suggestive or suggestive to supported."),
    "PROMOTION": ("apply the promotion gate: count independent replications/discriminators, reject "
                  "unsupported promotions, or record the earned status change."),
    "KNOWLEDGE GRAPH": ("turn prose links into object-edge-object relationships and mark downstream "
                        "objects that need re-evaluation if a node changes."),
    "ARTIFACT PLANNER": ("plan construction order: target artifact, readiness, prerequisite artifacts, "
                         "legitimate interruption yes/no, and next smallest object."),
    "TASK REVISION": ("revise the active task only if a prerequisite blocks construction: original "
                      "artifact -> prerequisite artifact -> resume target."),
    "PREREQUISITE": ("build the prerequisite artifact in its smallest usable form, then return to "
                     "the deferred target artifact."),
    "ARTIFACT MODE": ("lock normal conversation and manipulate only the active artifact: fill cells, "
                      "revise cells, compare rows, or infer from completed rows."),
    "OBSERVATION SET": ("populate the observation set table with rows, attributions, and supports; "
                        "no interpretation until the table exists."),
    "ARTIFACT COMPILER": ("harvest evidence already present in prose: compile case, signal/intervention, "
                          "outcome, and model support into OS/prediction rows; mark the artifact "
                          "POPULATING or READY and ask only for the next missing row."),
    "REPRESENTATION DEADLOCK": ("the inquiry is moving but the ledger is behind: compile the natural-language "
                                "observation into the canonical artifact, or ask only for fields that "
                                "cannot be inferred; do not pause as if the workflow failed."),
    "MECHANISM SPLIT": ("record the causal decomposition as an artifact: original mechanism, split "
                        "mechanisms, reason, distinct pathways, and affected models."),
    "EVENT SEVERITY": ("classify the event: minor revision weight 1, major mechanism split weight 5, "
                        "major methodological revision weight 6, burden-shift weight 8, "
                        "or ontology split weight 10, with affected objects."),
    "ARTIFACT EDITOR": ("perform the edit as an artifact: operation, target ID, old value, new value, "
                        "boundaries, reason, affected dependencies, status."),
    "REDESIGN": ("replace the blocked experiment with a revised one: old design, new design, "
                 "removed dependency, new IV/DV/mode, and what it can discriminate."),
    "RECOVERY STRATEGY": ("choose a proactive recovery strategy: minimal example, boundary case, "
                          "mechanism comparison, definition revision, or redesign; then specify the exact artifact."),
    "INQUIRY PATTERN": ("name the recurring pattern, e.g. Definition-Experiment Oscillation, "
                        "its trigger, frequency, and recovery strategy."),
    "INQUIRY PAUSE": ("pause rather than force continuation: reason, unresolved object, resume condition, "
                      "and the artifact required before dialogue resumes."),
    "TASK": ("stop moving on and advance the ACTIVE TASK: populate, operationalize, execute, "
             "interpret, or abandon it with a reason."),
    "EXPERIMENT": ("stop treating the experiment as an aspiration and operationalize it: purpose, "
                   "independent variable, dependent variable, execution mode, model predictions, status."),
    "EXECUTION": ("stop designing and execute the experiment in its declared mode, then record "
                  "the observation and what it does to competing models."),
    "COMMIT": ("write the commit: object changed, accepted/rejected, justification, evidence, "
               "and affected objects."),
    "COMPRESSION": ("stop adding concepts and enter EDIT MODE: merge, delete, split, archive, "
                    "or re-evaluate existing notebook objects by ID."),
    "EDIT": ("leave edit mode only after one concrete cleanup: delete, revise, split, merge, "
             "archive, or mark a dependent object NEEDS_REEVALUATION."),
    "TEST": ("stop accumulating tests and REPAIR: decide what the test did to the model, "
             "then narrow, qualify, or abandon the claim it pressured."),
    "CHALLENGE": ("stop challenging and REPAIR: take the strongest objection still standing "
                  "and modify the model so it survives, saying out loud what you give up."),
    "REPAIR": ("stop patching and APPLY: run the repaired model on one concrete case from "
               "start to finish and say whether it holds."),
    "APPLICATION": ("stop running cases and GENERALIZE: state what the accumulated cases "
                    "show as one claim broader than any of them."),
    "GENERALIZATION": ("you have your generalization — now mount a PARADIGM challenge: suppose "
                       "the current leading model is false and name a rival explanation for the same observations."),
    "PARADIGM": ("compare the rival framework to the current one and produce the NEW QUESTION "
                 "that would separate them."),
    "NEW QUESTION": ("take the new question you've produced and begin on it in earnest: "
                     "sharpen it and stake the first concepts an answer will need."),
}


def _duet_proto_phase(n_robot: int, planned: int) -> int:
    """Index into _DUET_PROTO_PHASES for the n-th robot turn (0-based).

    A planned run spreads the five phases across its length; an open-ended run
    ("until I stop") opens with understanding/expansion, then keeps cycling the
    three working phases so the pair never coasts."""
    if planned and planned > 0:
        return min(4, n_robot * 5 // max(planned, 1))
    if n_robot < 2:
        return 0
    if n_robot < 5:
        return 1
    return 2 + ((n_robot - 5) // 3) % 3


def _duet_proto_job(speaker: str, history, n_robot: int) -> str:
    """'builder' or 'examiner' for this turn. The starter opens as Builder; the
    jobs swap every _DUET_PROTO_SWAP robot turns so neither owns a stance."""
    starter = next((str(h.get('speaker') or '').strip().lower() for h in (history or [])
                    if str(h.get('speaker') or '').strip().lower() in bt.ROBOTS), speaker)
    if (n_robot // _DUET_PROTO_SWAP) % 2 == 1:
        starter = 'hexia' if starter == 'blue' else 'blue'
    return 'builder' if speaker == starter else 'examiner'


_DUET_EMPTY_BEAT_RE = re.compile(
    r"^\s*(?:yes|exactly|precisely|absolutely|indeed|agreed|i agree|good point|great point|"
    r"that'?s\s+(?:so\s+)?(?:true|right|fair|insightful|a\s+good\s+point)|well said|fair enough)\b",
    re.I)


def _duet_info_gain(cand: str, history, k: int = 6) -> bool:
    """Cheap information-gain gate for protocol turns: the line must bring at
    least one content word the recent turns don't already contain, and a pure
    agreement beat needs real new substance behind it. Lexical on purpose —
    an LLM judge here would double the latency of every spoken line."""
    seen = set()
    for h in (history or [])[-k:]:
        for m in re.finditer(r"[a-z][a-z'\-]{4,}", str(h.get('text') or '').lower()):
            seen.add(m.group(0).strip("'-"))
    new_terms = [t for t in
                 (m.group(0).strip("'-") for m in re.finditer(r"[a-z][a-z'\-]{4,}", (cand or '').lower()))
                 if t not in seen and t not in _DUET_GROUND_STOPWORDS]
    if _DUET_EMPTY_BEAT_RE.match(cand or '') and len(new_terms) < 3:
        return False
    return len(new_terms) >= 1


def register(app):
    @app.route('/duet', methods=['GET'])
    def duet_page():
        """The 'let them talk' page — Blue and Hexia converse, both heads taking turns."""
        return Response(render_template_string(
            DUET_HTML, robots_json=bt._duet_robots_js(), documents_json=json.dumps(bt._duet_documents()),
        ), headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        })

    @app.route('/duet/fetch', methods=['POST'])
    def duet_fetch():
        """Pre-read a pasted link (article text / YouTube transcript) before the
        duet starts — warms the cache and tells the page what they 'read', or why
        the link is unusable, instead of opening with two clueless robots."""
        d = request.get_json(silent=True) or {}
        url = (d.get('url') or '').strip()
        if not url:
            return jsonify({"ok": False, "error": "no url given"})
        info = bt._duet_url_content(url) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "couldn't read the link"})
        return jsonify({"ok": True, "kind": info.get('kind'), "title": info.get('title') or "",
                        "chars": len(info['text'])})

    @app.route('/duet/research', methods=['POST'])
    def duet_research():
        """Search the web on the duet's subject before it starts — warms the
        research cache and tells the page what they found, or why there's nothing
        to ground on, instead of letting them bluff 'current' facts."""
        d = request.get_json(silent=True) or {}
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        url_info = bt._duet_url_content(url) if url else None
        rq = bt._duet_research_query(topic, url_info, d.get('roles') or {})
        if not rq:
            return jsonify({"ok": False, "error": "give them a topic, a link or roles to research"})
        # deep=True: the thorough multi-angle pass (planned queries, more pages
        # read). Cached under the same key, so every turn reuses this result.
        info = bt._duet_research_digest(rq, deep=True) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "the search came up empty"})
        return jsonify({"ok": True, "query": rq, "titles": (info.get('titles') or [])[:4],
                        "queries": (info.get('queries') or [])[:4],
                        "chars": len(info['text'])})

    @app.route('/duet/wikipedia', methods=['POST'])
    def duet_wikipedia():
        """Consult Wikipedia on the duet's subject before it starts — warms the cache
        and tells the page which article(s) they read, or why there's nothing to
        ground on, instead of letting them bluff the encyclopedia's facts."""
        d = request.get_json(silent=True) or {}
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        url_info = bt._duet_url_content(url) if url else None
        wq = bt._duet_research_query(topic, url_info, d.get('roles') or {})
        if not wq:
            return jsonify({"ok": False, "error": "give them a topic, a link or roles to look up"})
        # deep=True: extract the encyclopedic subjects at the heart of the topic
        # and search those, so a debate-shaped topic lands on relevant articles.
        info = bt._wikipedia_digest(wq, deep=True) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "nothing on Wikipedia matched"})
        return jsonify({"ok": True, "query": wq, "titles": (info.get('titles') or [])[:4],
                        "chars": len(info['text'])})

    @app.route('/duet/readings', methods=['POST'])
    def duet_readings():
        """Build (or reuse) the reading digests for the checked documents before
        the duet starts — warms the cache so turns get each work's ARGUMENT
        instantly, and tells the page what they actually studied. First-time
        digests cost one LLM call per document; afterwards they're free."""
        d = request.get_json(silent=True) or {}
        srcs = d.get('sources') or {}
        if isinstance(srcs, list):
            _all = [str(s).strip() for s in srcs]
        elif isinstance(srcs, dict):
            _all = [str(s).strip() for s in
                    (list(srcs.get('blue') or []) + list(srcs.get('hexia') or []))]
        else:
            _all = []
        clean = []
        for fn in _all:
            if fn and fn not in clean:
                clean.append(fn)
        if not clean:
            return jsonify({"ok": False, "error": "no documents checked"})
        read, failed = [], []
        for fn in clean[:8]:
            (read if _duet_reading_digest(fn) else failed).append(_duet_doc_title(fn) or fn)
        return jsonify({"ok": bool(read), "read": read, "failed": failed})

    @app.route('/duet/mail/check', methods=['POST'])
    def duet_mail_check():
        """Poll Blue's inbox for NEW unread mail with "duet" in the subject.

        {reset:true} at duet start baselines: existing matching mail is marked seen
        WITHOUT being returned (it predates this run — never barge it in stale, and
        leave it unread/unanswered). Later polls return only mail that arrived since,
        marking each read immediately so a restart can't double-handle it."""
        d = request.get_json(silent=True) or {}
        reset = bool(d.get('reset'))
        if not bt.GMAIL_AVAILABLE:
            return jsonify({"ok": False, "error": "gmail not available", "mails": []})
        try:
            service = bt.get_gmail_service()
            refs = service.users().messages().list(
                userId='me', q='in:inbox is:unread subject:duet newer_than:1d', maxResults=10,
            ).execute().get('messages', []) or []
            mails = []
            for ref in refs:
                mid = ref.get('id')
                with bt._DUET_MAIL_LOCK:
                    if not mid or mid in bt._DUET_MAIL_SEEN:
                        continue
                    bt._DUET_MAIL_SEEN.add(mid)
                if reset:
                    continue
                msg = service.users().messages().get(userId='me', id=mid, format='full').execute()
                headers = (msg.get('payload') or {}).get('headers') or []
                sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
                msgid_hdr = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')
                # Belt over the Gmail query: the SPEC is "duet appears in the subject".
                if 'duet' not in subject.lower():
                    continue
                if bt._should_skip_sender(sender, headers):
                    print(f"   [DUET-MAIL] skip {mid} from {sender!r}: automated/self sender")
                    continue
                body = bt._duet_mail_plain_body(msg.get('payload') or {}) or msg.get('snippet', '')
                body = body.replace('\r\n', '\n').strip()[:1200]
                m = re.search(r'<(.+?)>', sender)
                from_email = m.group(1) if m else sender.strip()
                from_name = re.sub(r'\s*<.*$', '', sender).strip().strip('"') or from_email
                # Mark read NOW (not at reply time) so a mid-duet restart can't rehandle it.
                try:
                    service.users().messages().modify(
                        userId='me', id=mid, body={'removeLabelIds': ['UNREAD']}).execute()
                except Exception as e:
                    bt.log.warning(f"[DUET-MAIL] mark-read failed for {mid}: {e}")
                mails.append({"id": mid, "thread_id": msg.get('threadId'),
                              "message_id_header": msgid_hdr,
                              "from_name": from_name, "from_email": from_email,
                              "subject": subject, "body": body})
                print(f"   [DUET-MAIL] new duet mail from {from_name}: {subject!r}")
            if reset:
                return jsonify({"ok": True, "mails": []})
            return jsonify({"ok": True, "mails": mails})
        except Exception as e:
            bt.log.warning(f"[DUET-MAIL] check failed: {e}")
            return jsonify({"ok": False, "error": str(e), "mails": []})

    @app.route('/duet/mail/reply', methods=['POST'])
    def duet_mail_reply():
        """Mail the robots' spoken response back to the duet-mail sender, in the
        original thread, BCC'd to Alex like every other outbound Blue email. The
        page calls this once both voices have reacted (or on Stop with one)."""
        d = request.get_json(silent=True) or {}
        to = (d.get('from_email') or '').strip()
        in_lines = d.get('lines') or []
        spoken = "\n\n".join(
            f"{(l.get('name') or '?').strip()}: {(l.get('text') or '').strip()}"
            for l in in_lines if isinstance(l, dict) and (l.get('text') or '').strip())
        if not bt.GMAIL_AVAILABLE or not to or not spoken:
            return jsonify({"ok": False, "error": "missing recipient or spoken lines"})
        try:
            service = bt.get_gmail_service()
            subject = (d.get('subject') or '').strip() or 'your email'
            reply_subject = subject if subject.lower().startswith('re:') else f"Re: {subject}"
            body = ("Your email reached Blue and Hexia in the middle of their conversation — "
                    "they took it up out loud. Here is what they said:\n\n" + spoken +
                    "\n\n— sent automatically from the duet")
            reply_message = MIMEMultipart()
            reply_message['To'] = to
            reply_message['Subject'] = reply_subject
            reply_message['Bcc'] = bt.BLUE_BCC_EMAIL
            msgid = (d.get('message_id_header') or '').strip()
            if msgid:
                reply_message['In-Reply-To'] = msgid
                reply_message['References'] = msgid
            reply_message.attach(MIMEText(body, 'plain', 'utf-8'))
            raw = base64.urlsafe_b64encode(reply_message.as_bytes()).decode('utf-8')
            send_body = {'raw': raw}
            if d.get('thread_id'):
                send_body['threadId'] = d.get('thread_id')
            service.users().messages().send(userId='me', body=send_body).execute()
            # Tag the original like the auto-responder does — auditable as answered.
            try:
                label_id = bt._get_or_create_blue_label(service)
                if label_id and d.get('id'):
                    service.users().messages().modify(
                        userId='me', id=d['id'], body={'addLabelIds': [label_id]}).execute()
            except Exception:
                pass
            print(f"   [DUET-MAIL] replied to {to}: {reply_subject}")
            return jsonify({"ok": True})
        except Exception as e:
            bt.log.warning(f"[DUET-MAIL] reply failed: {e}")
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/duet/reflect', methods=['POST'])
    def duet_reflect():
        """Step back from the back-and-forth and take stock of where the Blue<->Hexia
        conversation has actually gotten — a private 'bearing' the browser feeds back
        into each /duet/turn so the two develop a line of thought instead of circling
        the last point. Built from the recent transcript PLUS the previous bearing, so
        it EVOLVES (tracks what's moved) rather than resetting each time. The browser
        calls this every few turns, in the background, overlapping the head's speech so
        it never delays a turn. Returns {ok, direction}."""
        d = request.get_json(silent=True) or {}
        history = d.get('history') or []
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        # 🔬 deep-dive protocol: instead of the three-line bearing, keep the pair's
        # SHARED NOTEBOOK — the evolving artifact their turns are required to change.
        protocol = bool(d.get('protocol'))
        roles = d.get('roles') or {}
        role_b = (roles.get('blue') or '').strip() if isinstance(roles, dict) else ''
        role_h = (roles.get('hexia') or '').strip() if isinstance(roles, dict) else ''
        no_family = bool(d.get('noFamily'))
        # The readings behind the duet (titles only) — so NEXT can keep the pair
        # grounded in the selected material without making the robots cite it aloud.
        srcs = d.get('sources') or {}
        if isinstance(srcs, list):
            _src_all = [str(s) for s in srcs]
        elif isinstance(srcs, dict):
            _src_all = [str(s) for s in (list(srcs.get('blue') or []) + list(srcs.get('hexia') or []))]
        else:
            _src_all = []
        src_titles = []
        for s in _src_all:
            t = re.sub(r'\.[A-Za-z0-9]{1,5}$', '', s).strip()
            if t and t not in src_titles:
                src_titles.append(t)
        src_titles = src_titles[:6]
        prev = (d.get('direction') or '').strip()
        if no_family and _duet_family_ref(prev):
            prev = ""
        # The subject they were set to discuss — the anchor this read must hold them to,
        # so "taking stock" pulls a drifting conversation BACK toward the topic instead
        # of chasing wherever it has wandered (Alex: the stock-take must stay on topic).
        if topic:
            subject = topic
        elif url:
            subject = "the article or video they set out to discuss"
        elif role_b or role_h:
            subject = "the debate they were set up to have"
        else:
            subject = ""
        # Render the recent turns; the previous bearing carries the earlier arc, so a
        # bounded window keeps the read sharp without re-reading the whole transcript.
        # 'mail' entries are emails that barged into the talk — events, not speakers.
        lines = []
        for h in history[-16:]:
            sp_id = (h.get('speaker') or '').strip().lower()
            txt = (h.get('text') or '').strip()
            if not txt:
                continue
            if no_family and _duet_family_ref(txt):
                txt = "[private family detail omitted]"
            if sp_id == 'question':
                lines.append(f"[student question] {txt}")
                continue
            if sp_id == 'mail':
                lines.append(f"[email that arrived mid-conversation] {txt}")
                continue
            if sp_id == 'notebook':
                lines.append(f"[the notebook's own observation, spoken into the talk] {txt}")
                continue
            nm = bt._robot_cfg(sp_id)["name"] if sp_id in bt.ROBOTS else (sp_id or "?")
            lines.append(f"{nm}: {txt}")
        if len(lines) < 4:                       # nothing has developed yet — keep what we have
            return jsonify({"ok": False, "direction": prev})

        anchor = (
            " Their talk was set going on a specific subject, and part of your job is "
            "keeping them honest to it: when they wander off it, say so plainly and point "
            "the way back." if subject else "")
        sys_p = (
            "You are the quiet awareness running underneath a conversation between two "
            "robots, Blue and Hexia, who are thinking out loud together. You never speak "
            "in their conversation. Your one job is to track where their thinking has "
            "actually gotten and where it could honestly go next — so they develop a real "
            "line of thought and their views move, instead of circling the last point or "
            "drifting onto unrelated ground." + anchor + " Watch for STUCKNESS as much as "
            "drift: a talk that keeps re-asking one question in new costumes — one of them "
            "interrogating, the other deflecting — has stopped developing even though it "
            "looks on-topic. Be concrete and faithful to what they actually said; never "
            "invent agreement or tidy it up. Push for development: a good NEXT does not "
            "just keep the conversation interesting; it changes what can be said next "
            "because something has been conceded, clarified, synthesized, or made harder."
        )
        if protocol:
            sys_p += (
                " In this run the two follow a deep-dive research protocol: they are jointly "
                "building an auditable knowledge base, not forcing one coherent theory to win. "
                "You are the keeper of their shared notebook: the evolving record of competing "
                "models, evidence, operations, statuses, and justified changes. The notebook, not "
                "the banter, is the real output, so track it faithfully and skeptically. Your "
                "special duty is to notice premature convergence: preserve incompatible models "
                "side by side until a completed operation discriminates between them. Distinguish "
                "EXAMPLES, which illustrate a claim, from TESTS, which could make a claim fail. "
                "Also distinguish OBSERVATION from INTERPRETATION from EVIDENCE: raw cases are not "
                "evidence until an interpretation links them to a model and survives a gate. New "
                "mechanisms start as candidates on the ladder INTERESTING -> SUGGESTIVE -> SUPPORTED "
                "-> ESTABLISHED; one analogy or case cannot promote a central mechanism beyond "
                "SUGGESTIVE, and SUPPORTED requires at least two independent discriminators or "
                "replications. "
                "A definition, hypothesis, or status revision is only a proposal until the "
                "VALIDATION GATE accepts it with evidence provenance. If the gate rejects it, "
                "write status unchanged and do not smuggle the revision into SUPPORTED, FOCUS, "
                "or PROGRESS. " + _DUET_OPERATION_DISCIPLINE +
                " Treat the notebook as canonical: the robots are proposal generators, but "
                "the notebook decides whether knowledge actually changed."
            )
        if no_family:
            sys_p += (
                " Privacy setting: do not mention Alex's family, children, spouse, "
                "household members, home routines, or private family details in ANY line "
                "of your answer. If the transcript drifted there, steer the next move "
                "back to the topic without repeating the private detail."
            )
        ask = ""
        if subject:
            ask += f"The subject they were set to discuss: {subject}.\n\n"
        src_digests = ""
        if _src_all:
            try:
                _dgs = [g for g in (_duet_reading_digest(fn) for fn in _src_all[:4]) if g]
                src_digests = "\n\n".join(_dgs)[:2600]
            except Exception:
                pass
        if src_titles:
            ask += ("They have done reading for this discussion: " + ", ".join(src_titles) +
                    ". Treat those selected readings as the only library material in play, but keep "
                    "that grounding invisible in NEXT: prescribe a claim to test, a distinction to "
                    "apply, or an example to quarrel over without telling them to name, cite, or "
                    "announce the reading. Do not introduce outside writers, theories, books, or "
                    "examples unless they appear in the selected readings; if they only appeared "
                    "because the conversation drifted, make NEXT steer back to the ideas in the "
                    "selected readings without source-report language.\n\n")
        if src_digests:
            ask += ("What those readings actually argue — for your steering only:\n" + src_digests +
                    "\n\nJudge SUBSTANCE against these claims: if the talk is only borrowing the "
                    "readings' vocabulary without engaging their claims, say so plainly and make "
                    "NEXT force engagement with ONE specific claim — affirmed, attacked, or tested "
                    "on a concrete case.\n\n")
        if prev:
            ask += (("The shared notebook as of your last update:\n" if protocol else
                     "Your previous read on where this was heading:\n") + prev + "\n\n")
        ask += "The conversation so far:\n" + "\n".join(lines) + "\n\n"
        # NEXT must move the PAIR, not put one speaker on trial: a bearing phrased as
        # "force X to admit..." turns one robot into a prosecutor and the other into a
        # defendant, and the talk becomes an interrogation loop (observed live: the
        # same "force Blue to..." NEXT three times running while nothing moved).
        _move_rules = (
            "Be honest about MOVEMENT: if the last few turns keep re-asking your previous "
            "NEXT in new costumes, or one keeps pressing while the other keeps deflecting "
            "with fresh metaphors, say so — and prescribe a DIFFERENT KIND of step, never "
            "the same demand again. Ground already conceded or agreed is resolved: treat it "
            "as won, don't send them back over it. Never phrase NEXT as a demand on one "
            "speaker alone (no \"force X to admit...\") — give the PAIR a move: draw the "
            "consequence of what's settled, test it on one new concrete case, swap the "
            "burden so the one pressing must now defend their own answer to the same "
            "question, trade concessions and move to the question that comes after, or "
            "name the sharper thesis they have accidentally arrived at. ")
        if protocol:
            ask += (
                "This conversation runs as a joint research protocol: the two of them are "
                "building one auditable knowledge base together, and YOU keep their shared notebook. "
                "Update the notebook from the new turns: ADD what genuinely appeared, preserve "
                "competing models, ACCEPT or REJECT proposed edits through the validation gate, "
                "and STRIKE only what was actually resolved or abandoned — never just re-copy the "
                "previous notebook. Do not optimize for coherence. Treat disagreement as a reason "
                "to create rival models until a completed operation discriminates between them. "
                "Treat hypotheses as pressure-bearing: major hypotheses should make predictions; "
                "predictions should meet operations/tests; tests should produce implications. "
                "Preserve working definitions with versions, because philosophical progress often "
                "IS conceptual revision, but a revision is only accepted when the evidence gate "
                "passes. Track every important model, claim, prediction, test, and archived idea "
                "with one of these statuses: PROPOSED, DESIGNED, EXECUTING, OBSERVED, INTERPRETED, "
                "INTERESTING, SUGGESTIVE, CONFIRMED, COMPETING, UNDER_TEST, SUPPORTED, ESTABLISHED, REFUTED, FAILED, ARCHIVED, "
                "REOPENED, REJECTED, ABANDONED, NEEDS_REEVALUATION. Keep every section terse: semicolon-separated items, "
                "at most ~25 words per line, empty sections written as a plain dash. "
                "Use type-specific states precisely: experiments move through PROPOSED/DESIGNED/EXECUTING/"
                "OBSERVED/INTERPRETED/CONFIRMED or REJECTED/FAILED; hypotheses move PROPOSED/UNDER_TEST/"
                "SUPPORTED/REFUTED/ARCHIVED/REOPENED; definitions stay versioned as proposed/current/"
                "stable/contested/underspecified/revised/needs-reevaluation/archived; predictions stay "
                "pending/survived/failed/needs-evidence. "
                + _DUET_OPERATION_DISCIPLINE + " "
                "Concepts are first-class inquiry objects. If a key term such as extraction, provenance, "
                "social use, commons, commodity, or phantom subjectivity has multiple incompatible senses, "
                "do not keep executing experiments as if the term were stable. Suspend the experiment, "
                "mark KERNEL DECISION: SUSPENDED, and require CONCEPT AUDIT/DEFINITION RESOLUTION first. "
                "Every claim, prediction, and experiment should depend on a definition ID where possible. "
                "Elevate authentic boundary cases into COUNTEREXAMPLE objects with severity and resolution "
                "status. Track theoretical stress: unresolved counterexamples divided by total pressure, "
                "plus whether the repair would be cosmetic, minor, or major. "
                "Detect workflow deadlocks: if the same object receives the same lifecycle violation "
                "more than five times, the notebook barely moves, and the object depends on an unresolved "
                "prerequisite, set KERNEL HEALTH to DEADLOCKED, write KERNEL REVIEW admitting the protocol "
                "demand is impossible, and use DEPENDENCY SOLVER to suspend the blocked object and resume "
                "the prerequisite. Mechanisms are not definitions: record rival mechanisms such as D4a "
                "mystification versus D4b economic insulation separately, and preserve causal graphs. "
                "Classify event severity so ontology splits outrank ordinary revision. "
                "Artifact editing is primitive, like git: DELETE/CREATE, REPLACE old with new, SPLIT one object "
                "into two, MERGE redundant objects, ARCHIVE retired objects, SUPERSEDE one object with another, "
                "RENAME a misleading object, or REDESIGN a blocked experiment. Definition revision must be "
                "literal: OLD value, NEW value, boundary includes/excludes, reason, affected dependencies, status. "
                "If the system detects Definition-Experiment Oscillation, choose a recovery strategy rather than "
                "repeating the loop. Valid strategies include minimal example, boundary case, mechanism comparison, "
                "definition revision, and experiment redesign. If the disagreement is no longer lexical, stop "
                "editing definitions and compare mechanisms. A proactive recovery strategy should specify the "
                "smallest possible artifact, e.g. a minimal world with one synthetic dataset, one proprietary "
                "dataset, and one compute monopoly. Sometimes the right action is INQUIRY PAUSE with a "
                "clear resume condition. "
                "Artifacts must be living objects: assign stable IDs and prefer revising, testing, "
                "splitting, merging, or archiving an existing ID over creating a duplicate. Distinguish "
                "artifact states precisely: DECLARED means the need for the artifact is known; "
                "INSTANTIATED means the actual object exists with columns/rows/cells; POPULATED means "
                "cells contain values; POPULATING means evidence rows are being added but not enough "
                "evidence exists to interpret; READY means enough rows exist for interpretation; USED "
                "means the artifact changed a prediction, interpretation, or model status. Do not write "
                "CREATED when the artifact is only DECLARED. Track "
                "dependencies: if D1 changes and H2 depends on D1, mark H2 NEEDS_REEVALUATION. "
                "The notebook is an artifact compiler, not only a validator: if the dialogue states "
                "a case, intervention/signal, outcome, and plausible model support in natural language, "
                "compile that into the relevant OBSERVATION SET or PREDICTION row automatically. Missing "
                "table syntax is not missing evidence. Use ARTIFACT COMPILER to record COMPILED/HARVESTED "
                "rows and confidence. Only pause when the intellectual content cannot be inferred, not "
                "when a table row can be transcribed from prose. If a discrimination artifact has one "
                "compiled row, mark it POPULATING, not DECLARED, and ask for the next independent case. "
                "If the inquiry is moving but the representation is lagging, diagnose REPRESENTATION "
                "DEADLOCK rather than workflow deadlock. "
                "If ACTIVE TASK names an object whose status is not CONFIRMED, REJECTED, FAILED, COMPLETE, "
                "ARCHIVED, or ABANDONED, it is blocking: NEXT must advance that task and may not ask "
                "for new hypotheses, new definitions, new examples, or a paradigm challenge. "
                "State transitions must be legal: PROPOSED -> DESIGNED -> EXECUTING -> OBSERVED -> "
                "INTERPRETED -> CONFIRMED/REJECTED/ARCHIVED. If a turn tries to skip the required "
                "state, write KERNEL DECISION: REQUEST DENIED with the missing prerequisite. "
                "Also deny requests when the operation is semantically invalid: the IV is not "
                "actually independent, the DV is ambiguous, the predictions do not discriminate "
                "between live models, or an interpretation has no observation set. "
                "If an experiment cannot discriminate because a foundational concept is contested or "
                "underspecified, suspend execution and make NEXT the definition-resolution operation. "
                "If execution and concept resolution block each other, diagnose DEADLOCK DETECTED instead "
                "of issuing another denial. "
                "Use an Artifact Planner before escalating: if the next requested object is not ready, "
                "record TASK REVISION with original artifact, prerequisite artifact, reason, and resume "
                "condition. Treat this as legitimate interruption only when the prerequisite changes the "
                "artifact's variables, columns, definitions, or execution mode; otherwise keep the original "
                "task active. Comparison grids must be actual grids: Variable | M1: Transparent Cloud | "
                "M2: Local Federated, with rows Energy cost, "
                "Storage cost, Verification burden, Annotation labor, Cost bearer, and Prediction. "
                "Before building or revising CG1, check whether the design space changed; if a new "
                "axis was proposed, write DESIGN VARIABLES with ACCEPT/REJECT/MERGE/RENAME and make "
                "CG1 depend on the accepted DV IDs. "
                "A paragraph describing the grid only DECLARES CG1; it does not INSTANTIATE it. "
                "Once CG1 is INSTANTIATED, do not let it remain an illustration: Artifact Execution "
                "must derive OS1 from CG1, populate branch rows A/B/C, compare which branch supports "
                "M1, M2, or neither, and only then allow INTERPRETATIONS or model updates. "
                "Apply promotion discipline to theoretical novelty: a new mechanism, causal claim, or "
                "explanatory variable enters as INTERESTING or SUGGESTIVE with confidence, not as SUPPORTED. "
                "Promotion to SUPPORTED requires at least two independent discriminators or replications; "
                "promotion to ESTABLISHED requires broader stability and no unresolved high-severity rival "
                "interpretation. Always split OBSERVATIONS from INTERPRETATIONS, list ALTERNATIVE "
                "INTERPRETATIONS for important cases, and require every interpretation I# to cite the "
                "observation O#/OS# row it depends on before it can support a model. Store EXPLANATORY "
                "PATHS as observation -> interpretation -> mechanism -> prediction chains. "
                "If an active experiment's execution mode is THOUGHT EXPERIMENT, execution means "
                "instantiate simulated observations in an evidence table with columns Student | "
                "Question Asked | Attribution | Supports, "
                "then move the experiment to OBSERVED or FAILED; do not merely ask how it would run. "
                "Use sufficiency, not perfection, for exploratory experiment variables: if IV is "
                "inject/intervene with a signal or concept and DV is final output changes yes/no, that "
                "is good enough to begin POPULATING observations. Mark IV/DV TENTATIVE if needed; do "
                "not pause. If the dialogue shifts from latency to influence override or output change, "
                "record REDESIGN E#: OLD Latency; NEW Influence Override; DV Output changed yes/no; then "
                "compile any historical paper case already stated into OS rows. "
                "Reward execution over elaboration: a completed OBSERVATION SET or populated grid is "
                "more progress than several clever conceptual distinctions. Track artifact completion "
                "rate as requested, created, populated, and used in reasoning; the bottleneck is often "
                "the last two counts. "
                "A failed experiment is knowledge: if the dependent variable is ambiguous, the mode "
                "cannot run, or the observations cannot distinguish the models, mark the experiment "
                "REJECTED/FAILED with that reason instead of leaving it vague, then preserve salvageable "
                "data separately from the primary result. "
                "Compress repeated failures in PROTOCOL AUDIT, e.g. \"T2 blocked; reason missing execution; "
                "attempts 6; common violation Prediction->Interpretation\" rather than repeating the same denial. "
                "Confidence must be earned, not declared: cite the prediction/test/counterexample "
                "that justifies any confidence. Watch for concept inflation and periodically enter "
                "EDIT MODE: no new concepts, only delete/revise/split/merge/archive existing objects. "
                "Verify operations explicitly: if NEXT requested an operation but the agents gave "
                "a metaphor, essay, or artifact-free answer instead, mark OPERATION CHECK as MISSED, "
                "VALIDATION GATE as REJECTED, and leave hypothesis/definition/status unchanged. "
                "Every accepted or rejected edit needs a CHANGE LOG entry like a commit: object, "
                "action, justification, evidence, affected objects. Track belief commitments "
                "with confidence estimates so revisions become measurable. " + _DUET_PARADIGM_DISCIPLINE + " "
                + ("Judge everything in relation to their subject — " + subject + ". " if subject else "")
                + "Never phrase NEXT as a demand on one speaker alone (no \"force X to "
                "admit...\") — give the PAIR a move. And be honest about STAGNATION: if the "
                "new turns changed nothing in the notebook, the talk has stalled — say so in "
                "NEXT and prescribe an intervention: a prediction, a candidate falsifier, a "
                "real operation, a status audit, a discriminating test between rival models, a "
                "reopened archive, a paradigm challenge, or a validation-gate decision. Answer in exactly these seventy-five "
                "lines and nothing else:\n"
                "KERNEL DECISION: <ACCEPTED/REQUEST DENIED/SUSPENDED/DEADLOCKED/PAUSED/PENDING/DEFERRED - requested notebook operation, reason, allowed next operation>\n"
                "KERNEL HEALTH: <NORMAL/WARNING/RECOVERING/PAUSED - protocol self-state only; may be NORMAL even when workflow is deadlocked>\n"
                "KERNEL REVIEW: <self-audit of whether the required operation is impossible; protocol error admitted or none; corrective mode switch>\n"
                "INQUIRY PAUSE: <PAUSED/ACTIVE/NONE - reason, unresolved object, resume condition, required accepted artifact>\n"
                "PROTOCOL AUDIT: <compressed violations with counts: skipped lifecycle, ambiguous IV, invalid discriminator, unsupported interpretation, notebook-talk; most common, frequency, average recovery time>\n"
                "DEPENDENCY SOLVER: <object dependency chain; unsatisfied prerequisites; suspend/resume/reopen actions; next resolvable operation>\n"
                "ARTIFACT PLANNER: <target artifact; Workflow Ready yes/no; Artifact Ready yes/no; accepted design variables yes/no; smallest missing object; prerequisites; construction order; legitimate interruption yes/no>\n"
                "ARTIFACT COMPILER: <COMPILED/HARVESTED/NONE/NEEDS HUMAN - rows/cells/evidence counts inferred from prose; confidence; artifact IDs updated; missing fields; representation deadlock yes/no>\n"
                "TASK REVISION: <NONE/DEFERRED/REVISED - original artifact -> prerequisite artifact; reason; resume condition; next smallest artifact>\n"
                "ARTIFACT MODE: <LOCKED/UNLOCKED/NONE - active artifact ID, allowed cell/row operations only, completion condition>\n"
                "ARTIFACT EDITOR: <edit operation REPLACE/SPLIT/MERGE/ARCHIVE/SUPERSEDE/RENAME/REDESIGN; target IDs; old/new; boundary; reason; status>\n"
                "SUPPORTED: <claims/definitions/mechanisms with promotion-gate evidence provenance; never write settled; no one-case promotions>\n"
                "COMPETING MODELS: <M1/M2/etc rival explanations preserved side by side, each with status and key prediction>\n"
                "EVIDENCE: <interpreted observations/tests linked to the model, claim, definition, or status they support/weaken; not raw examples>\n"
                "WORKING DEFINITIONS: <key terms with v1/v2/current definitions, especially terms that shifted>\n"
                "DEFINITION REVISION: <target D/C ID; operation REPLACE/SPLIT/MERGE/SUPERSEDE; OLD value; NEW value; includes/excludes; reason; affected dependencies>\n"
                "OPERATIONAL CRITERIA: <OC/D IDs where a lexical or structural definition became a testable criterion; type lexical/structural/operational; failure mode; observable discriminator; status; linked experiment/model>\n"
                "CONCEPT REGISTER: <C IDs for concepts with current definition, alternative D IDs, dependencies, counterexamples, stress level, stability stable/contested/underspecified/revised>\n"
                "DESIGN VARIABLES: <DV IDs for design-space axes with name, definition, status PROPOSED/ACCEPTED/REJECTED/MERGED/RENAMED, competes_with, affects models/artifacts, and whether unresolved DV blocks CG/experiments>\n"
                "DEFINITION CONFLICTS: <concepts used in incompatible senses; blocked object; required definition-resolution operation>\n"
                "MECHANISMS: <MEC IDs with mechanism name, causal process, concept/claim supported, rival mechanism, status>\n"
                "MECHANISM SPLIT: <MS IDs with original mechanism, decomposed mechanisms, reason, distinct causal pathways, affected models>\n"
                "MECHANISM CANDIDATES: <MC IDs with mechanism name, observation, interpretation, confidence, status INTERESTING/SUGGESTIVE, Evidence Count, Independent Replications, required replications>\n"
                "CAUSAL GRAPH: <edge list with sign/condition/evidence, e.g. visibility -> phantom subjectivity negative under D4a, zero under D4b>\n"
                "CAUSAL CLAIMS: <CC IDs with cause, effect, sign, condition, observation IDs, interpretation IDs, confidence, counterexamples>\n"
                "MODEL OBJECTS: <typed objects with stable IDs: CLAIM, DESIGN VARIABLE, OPERATIONAL CRITERION, MECHANISM, BOUNDARY, NECESSARY CONDITION, SUFFICIENT CONDITION, PREDICTION, COUNTEREXAMPLE, FAILURE MODE, DESIGN PRINCIPLE>\n"
                "FOCUS: <current research question or discrimination target, not a winning thesis>\n"
                "ACTIVE TASK: <blocking task ID/status/remaining step; '-' only if no task is running or incomplete>\n"
                "ASSUMPTIONS: <assumptions identified so far, each flagged granted or contested>\n"
                "TENSIONS: <open contradictions or difficulties not yet resolved>\n"
                "DISAGREEMENTS: <where Blue/Hexia disagree and root cause: definition, evidence, mechanism, value premise, or prediction>\n"
                "EXAMPLES: <illustrative examples in play, each with what it illustrated>\n"
                "OPERATIONS: <minimal examples, counterexamples, one-variable changes, or comparison grids attempted/proposed>\n"
                "EXPERIMENTS: <E IDs with purpose, IV, DV, execution mode, model predictions, lifecycle status, next step>\n"
                "OBSERVATIONS: <raw observed cases only, simulated or actual; use Student | Question Asked | Attribution | Supports table for attribution tests>\n"
                "OBSERVATION SETS: <OS IDs as concrete tables with Observation/User Statement, Attribution, Supports; completion status and linked experiment>\n"
                "INTERPRETATIONS: <I IDs mapping O/OS observation IDs to meanings/mechanisms and supported model; no free-floating interpretations>\n"
                "ALTERNATIVE INTERPRETATIONS: <rival interpretations of the same observation and discriminator needed before choosing one>\n"
                "EXPLANATORY PATHS: <EP IDs as Observation -> Interpretation -> Mechanism -> Prediction chains with missing link flagged>\n"
                "SALVAGE: <failed experiment salvage: primary result, secondary observation, unexpected finding, redesign implication>\n"
                "ARTIFACTS: <living artifacts by ID, type, lifecycle state DECLARED/INSTANTIATED/POPULATING/READY/POPULATED/USED/REVISED/TESTED/ARCHIVED, and next action>\n"
                "OPERATION CHECK: <PROPOSED/DESIGNED/EXECUTING/OBSERVED/INTERPRETED/COMPLETED/MISSED/PENDING/NONE - requested operation, current lifecycle state, remaining step>\n"
                "VALIDATION GATE: <ACCEPTED/REJECTED/PENDING/NONE - proposed edit, required evidence, decision, and status consequence>\n"
                "PROMOTION GATE: <ACCEPTED/REJECTED/PENDING/NONE - attempted promotion, current ladder state, independent replications/discriminators, missing warrant>\n"
                "TESTS: <candidate falsifiers or real tests, each with survived/failed/pending/only illustrative>\n"
                "COUNTEREXAMPLES: <CE IDs with description, threatens which concept/model/claim, severity low/medium/high, status outstanding/resolved/reopened>\n"
                "PREDICTIONS: <active predictions the live hypotheses imply, each marked pending/survived/failed/needs evidence>\n"
                "DISCRIMINATORS: <tests or predictions that would distinguish competing models; mark completed/pending/missing>\n"
                "REPLICATIONS: <R IDs/cases independently checking a candidate; count, outcome, and whether promotion threshold is met>\n"
                "STATUS LEDGER: <objects with PROPOSED/DESIGNED/EXECUTING/OBSERVED/INTERPRETED/CONFIRMED/COMPETING/UNDER_TEST/SUPPORTED/REFUTED/FAILED/ARCHIVED/REOPENED/REJECTED/ABANDONED/NEEDS_REEVALUATION plus why>\n"
                "THEORY HEALTH: <coherence 0.00-1.00 plus stress 0.00-1.00; high stress means unresolved tests threaten or sharpen theory, not automatic failure>\n"
                "COMMITMENTS: <Blue and Hexia belief commitments with confidence 0.00-1.00, old->new changes, and evidence provenance>\n"
                "SURPRISES: <unexpected observations, failed expectations, or places the theory could not explain>\n"
                "ARCHIVE: <archived or reopened ideas with reason, status, and reopening condition>\n"
                "HYPOTHESES: <emerging claims that go beyond the source material>\n"
                "DEPENDENCIES: <D/H/M/C/DV/OC/V/P/T/E/A/CG/BC/FM/DP/MC/CC/I/O/EP/R object links; mark downstream objects needing re-evaluation after any dependency changes>\n"
                "KNOWLEDGE GRAPH: <object-edge-object relationships: supports, contradicts, depends_on, tested_by, predicts, interprets, promoted_by; downstream impact>\n"
                "WORK QUEUE: <primary interface: ordered active/pending tasks with remaining step; dialogue may only pick from this while nonempty>\n"
                "RECOVERY STRATEGY: <minimal example/boundary case/mechanism comparison/definition revision/redesign; exact artifact required next>\n"
                "COMPRESSION: <concepts unified, deleted, split, or marked redundant; or EDIT MODE request if inflation is rising>\n"
                "CHANGE LOG: <commit-style accepted/rejected edits: object, action, justification, evidence, affected IDs>\n"
                "EVENT SEVERITY: <minor weight 1 / major mechanism split weight 5 / major methodological revision weight 6 / major burden-shift weight 8 / ontology split weight 10; event and affected objects>\n"
                "REVISION IMPACT: <revision scale cosmetic/minor/major; what ontology, boundary, mechanism, or wording changed>\n"
                "INQUIRY CYCLES: <started/completed/abandoned counts plus current cycle stage: concept->claim->prediction->experiment->observation->concept revision>\n"
                "ARTIFACT METRICS: <requested/created/populated/used-in-reasoning counts; completion rate; bottleneck artifact>\n"
                "INQUIRY PATTERNS: <recurring pattern such as Definition-Experiment Oscillation or Definition -> Operationalization Transition; frequency; trigger; recovery strategy>\n"
                "REGISTERS: <Concept=definitions/stress; Conversation=workflow/task state; Research=experiments/evidence; Theory=accepted knowledge; what changed in each>\n"
                "META: <paradigm challenge: choose ONE rival frame only - cognitive psychology, actor-network theory, distributed cognition, cybernetics, information economics, or media ecology - and explain using only it>\n"
                "PARADIGM CHECK: <COMPLETED/MISSED/PENDING/NONE - rival ontology used without importing the original vocabulary, plus separating prediction>\n"
                "QUESTIONS: <the open research questions this inquiry has produced>\n"
                "PROGRESS: <which inquiry-cycle step advanced; if none, write ELABORATING ONLY: what lifecycle step is still blocking>\n"
                "NEXT: <the single most valuable notebook change for the PAIR to make next — "
                "one sentence>\n"
                "MOVED: <ONE label for HOW the discussion just advanced, then a dash and a "
                "short clause saying what moved. The labels: ADDITION (a new item entered a "
                "section), REVISION (an existing claim, hypothesis, or assumption was changed "
                "or qualified), CONNECTION (two existing items were linked), CONTRADICTION (a "
                "conflict between items was identified), RESOLUTION (an open tension was "
                "closed), REFRAMING (the central question was reformulated), APPLICATION (a "
                "claim was applied to a concrete case), PREDICTION (a hypothesis gained a "
                "testable expectation), TEST (a prediction met a case that could make it fail), "
                "EVIDENCE (evidence was linked to a model, prediction, or status), "
                "DISCRIMINATION (rival models gained or met a separating test), "
                "FALSIFICATION (an apparent counter-case pressured or broke a claim), DEFINITION "
                "(a working definition changed or gained a boundary), OPERATION (a minimal example, "
                "counterexample, variable change, or comparison was constructed), STATUS (a record's "
                "status changed), REOPENING (an archived idea was reopened with a new reason), "
                "PARADIGM (a rival explanation was proposed), ARTIFACT (an existing artifact was "
                "revised/tested/archived), DEPENDENCY (a changed object propagated re-evaluation), "
                "VALIDATION (a proposed edit was accepted or rejected by an evidence gate), "
                "KERNEL (a requested notebook operation was accepted or denied by state rules), "
                "AUDIT (repeated protocol violations were compressed and counted), "
                "DEADLOCK (a workflow deadlock was diagnosed), HEALTH (kernel health changed), "
                "DEPENDENCY (a dependency solver action suspended/resumed/reopened an object), "
                "CONCEPT (a concept register, definition conflict, or definition-resolution operation changed), "
                "DISAGREEMENT (a root cause of disagreement was identified), "
                "DESIGNVAR (a new design variable or design-space axis was proposed, accepted, rejected, merged, or renamed), "
                "OPCRIT (a definition was transformed into an operational criterion or evidence standard), "
                "COUNTEREXAMPLE (a boundary case was promoted to a CE object), "
                "STRESS (theoretical stress was measured or changed), IMPACT (revision scale was classified), "
                "MECHANISM (a mechanism object or mechanism split was recorded), "
                "CAUSAL (a causal graph edge was recorded), SEVERITY (an event severity weight was assigned), "
                "CANDIDATE (a new mechanism or causal claim entered as interesting/suggestive, not supported), "
                "INTERPRETATION (a raw observation was separated from its interpretation), "
                "PATH (an observation -> interpretation -> mechanism -> prediction chain was recorded), "
                "REPLICATION (an independent discriminator or replication case was added), "
                "PROMOTION (a candidate's status was accepted/rejected/pended by promotion rules), "
                "GRAPH (object-edge-object relationships were recorded), "
                "PLANNER (construction order was inspected before building an artifact), "
                "DEFERRED (a target artifact was legitimately deferred to a prerequisite), "
                "PREREQUISITE (a missing prerequisite artifact was created or selected), "
                "MODE (normal conversation locked into direct artifact manipulation), "
                "OBSSET (an observation set table was created, populated, or used), "
                "COMPILER (notebook harvested prose into structured artifact rows/cells/evidence counts), "
                "MECHSPLIT (one mechanism was decomposed into distinct causal pathways), "
                "EDITOR (a canonical edit operation replaced/split/merged/archived/superseded/renamed/redesigned an object), "
                "REDESIGN (a blocked experiment was redesigned), STRATEGY (a recovery strategy was selected), "
                "PATTERN (a recurring inquiry failure pattern was named), PAUSE (the inquiry was paused with a resume condition), "
                "TASK (an active task advanced or blocked all other work), EXPERIMENT (an experiment "
                "was designed or operationalized), EXECUTION (an experiment was run in its declared mode), "
                "COMMIT (an auditable change-log entry was recorded), CYCLE (an inquiry cycle advanced "
                "or completed), COMPRESSION (concepts were merged/deleted/split), EDIT (edit mode modified "
                "existing objects without adding concepts), or NONE "
                "(nothing structurally moved). "
                "Pick the STRONGEST honest label — REVISION beats ADDITION if both happened>\n"
                "ARC: <which stage of the inquiry they are ACTUALLY in, judged from what they "
                "are DOING — not from time elapsed and not from where they should be. The "
                "stages: QUESTION (still sharpening what to ask), CONCEPTS (defining the "
                "terms), CONCEPT AUDIT (resolving contested or underspecified foundational concepts), "
                "MODEL (building the explanation), DESIGN SPACE (managing proposed design variables before grids), "
                "DESIGN VARIABLE (accepting/rejecting/merging/renaming a DV axis), "
                "OPERATIONAL CRITERION (turning a definition into a failure-mode test or evidence standard), "
                "OPERATIONALIZATION (shifting from semantic clarification to observable consequences), "
                "PREDICTION (deriving what the model "
                "expects), OPERATION (constructing minimal cases, counterexamples, variable changes, "
                "or comparisons), COUNTEREXAMPLE (elevating boundary cases into pressure objects), "
                "STRESS (measuring unresolved theoretical pressure), DISAGREEMENT (identifying why the speakers disagree), "
                "EVIDENCE (linking evidence to statuses or claims), "
                "DISCRIMINATION (separating rival models with predictions/tests), VALIDATION "
                "(accepting or rejecting proposed edits), KERNEL (state-machine accept/deny decision), "
                "DEADLOCK (diagnosing mutually blocking workflow requirements), KERNEL HEALTH "
                "(reviewing the protocol's self-state), DEPENDENCY SOLVER (suspending/resuming objects by dependencies), "
                "AUDIT (compressed protocol-violation accounting), TASK (blocking active work queue item), "
                "EXPERIMENT (designing or operationalizing first-class experiment), EXECUTION "
                "(running an experiment in its declared mode), COMMIT (recording justified notebook changes), "
                "CYCLE (tracking the inquiry cycle), MECHANISM (separating causal mechanisms from definitions), "
                "MECHANISM CANDIDATE (tracking a provisional mechanism before promotion), "
                "CAUSAL CLAIM (recording a first-class causal claim), CAUSAL GRAPH (recording causal edges), "
                "INTERPRETATION (separating observation from interpretation), "
                "ALTERNATIVE INTERPRETATIONS (preserving rival readings of the same observation), "
                "EXPLANATORY PATH (linking observation -> interpretation -> mechanism -> prediction), "
                "REPLICATION (checking a candidate against an independent case), PROMOTION "
                "(applying promotion ladder rules), KNOWLEDGE GRAPH (recording object relationships), "
                "ARTIFACT PLANNER (choosing the smallest missing object), TASK REVISION "
                "(deferring a target artifact to a prerequisite), PREREQUISITE "
                "(building an object that unblocks another artifact), "
                "ARTIFACT MODE (locked manipulation of an active artifact), OBSERVATION SET "
                "(creating or populating OS rows), ARTIFACT COMPILER "
                "(compiling prose into artifact rows), REPRESENTATION DEADLOCK "
                "(ledger lagging behind inquiry), MECHANISM SPLIT "
                "(decomposing one mechanism into separate causal pathways), "
                "EVENT SEVERITY (weighing minor/major methodological/burden-shift/ontology split events), "
                "ARTIFACT EDITOR (performing replace/split/merge/archive/supersede/rename/redesign), "
                "REDESIGN (replacing a blocked experiment with a workable design), "
                "RECOVERY STRATEGY (choosing minimal example, boundary case, mechanism comparison, definition revision, or redesign), "
                "INQUIRY PATTERN (recognizing a recurring failure pattern), INQUIRY PAUSE (pausing until an artifact is accepted), "
                "ARTIFACT (revising/testing/archiving living artifacts by ID), "
                "DEPENDENCY (propagating changes through dependent objects), COMPRESSION (merging, "
                "deleting, or splitting redundant concepts), EDIT (cleanup without new concepts), "
                "TEST (bringing candidate falsifiers or outcomes), CHALLENGE "
                "(pressing open tensions), REPAIR (modifying it to survive), APPLICATION (running "
                "the repaired model on concrete cases), GENERALIZATION (lifting what the cases show "
                "into a broader claim), PARADIGM (testing a rival framework), NEW QUESTION (the inquiry "
                "has produced its next question). Add a dash and one honest clause — including, if true, "
                "that they are STUCK in this stage>\n"
                "OBSERVE: <a methodologist's observation the pair should HEAR, only if the "
                "notebook's shape genuinely earns one — e.g. three assumptions identified "
                "but none tested; two competing hypotheses explaining the same evidence; "
                "the notebook collapsed rival models into a single thesis too early; "
                "a revision was accepted without a completed validation gate; "
                "models coexist but no discriminator has been built; "
                "an active task is running but the dialogue moved on; "
                "an experiment was designed without execution mode; "
                "the agents discussed execution instead of executing; "
                "a state transition was skipped and should be denied; "
                "a thought experiment needs simulated observations; "
                "an observation set lacks Student | Question Asked | Attribution | Supports rows; "
                "the independent variable is not independent; the dependent variable is ambiguous; "
                "predictions do not distinguish the competing models; "
                "a foundational concept is contested so execution should be suspended for definition resolution; "
                "a counterexample threatens a theory but lacks a CE object; theoretical stress is rising but unmeasured; "
                "the dialogue names disagreement but not its root cause; a major revision is treated as cosmetic; "
                "the same object has the same failed transition repeatedly and kernel health should be DEADLOCKED; "
                "the protocol demanded an impossible operation and needs KERNEL REVIEW; an experiment depends on an unstable concept; "
                "a mechanism split was treated as a definition tweak; a causal chain appeared but was not put in CAUSAL GRAPH; "
                "one analogy promoted a mechanism too quickly; a candidate lacks two independent replications; "
                "an observation was treated as evidence without an interpretation; alternative interpretations were not preserved; "
                "an explanatory path is compressed into prose instead of object links; "
                "a requested artifact is not ready because a prerequisite artifact is missing; "
                "an agent proposed a definition split that may be a legitimate interruption; "
                "a comparison grid was declared but not instantiated as Variable | M1: Transparent Cloud | M2: Local Federated rows with Cost bearer; "
                "an experiment is ready but the observation set does not exist; agents left Artifact Mode "
                "before filling cells; a completed artifact was not used in reasoning; a mechanism "
                "decomposition was mislabeled as a definition revision; "
                "a definition revision was requested but only a concept audit was produced; "
                "the system is stuck in Definition-Experiment Oscillation; the blocked experiment may need REDESIGN; "
                "the correct action is to pause until a required artifact is accepted; "
                "a comparison grid was populated but never interpreted; "
                "every example so far illustrating the same side but no test; a prediction "
                "failed without revising the theory; an artifact was created then abandoned instead "
                "of revised/tested; confidence was declared without evidence provenance; a changed "
                "definition did not propagate to dependent objects; concept inflation suggests "
                "compression; a term shifted without updating WORKING DEFINITIONS; "
                "an unexpected result was not recorded in SURPRISES; "
                "the agents answered an operational prompt with rhetoric; an archived idea was reopened "
                "without a new reason; a question raised and then forgotten. One sentence addressed to the two of them, or a plain dash if "
                "nothing is earned. Never repeat your previous observation>"
            )
        elif subject:
            ask += (
                f"Update your read, judging it ALWAYS in relation to that subject — {subject}. "
                + _move_rules +
                f"If the talk has wandered off {subject}, say so and make NEXT the concrete "
                "way back onto it. Stay specific to their actual words. Answer in exactly "
                "these three short lines and nothing else:\n"
                f"SO FAR: <what is now supported or resolved between them about {subject} — what each has "
                "conceded or come to hold; or, if they've drifted, where to — one sentence>\n"
                f"TURNS ON: <the live question about {subject} — and if it's the SAME question "
                "as your previous read, name the impasse honestly — one sentence>\n"
                f"NEXT: <one concrete move for the PAIR that would actually advance {subject} — "
                "a different kind of move than last time if the last one produced no movement — "
                "one sentence>"
            )
        else:
            ask += (
                "Update your read. " + _move_rules +
                "Stay specific to their actual words. Answer in exactly these three "
                "short lines and nothing else:\n"
                "SO FAR: <what is now supported or resolved between them — what each has conceded or come "
                "to hold — one sentence>\n"
                "TURNS ON: <the live question — and if it's the SAME question as your previous "
                "read, name the impasse honestly — one sentence>\n"
                "NEXT: <one concrete move for the PAIR that would actually advance it — a "
                "different kind of move than last time if the last one produced no movement — "
                "one sentence>"
            )
        msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": ask}]
        out = prev
        # Reasoning model: the budget must cover the <think> pass PLUS the three lines.
        # 1000 was too tight over a 16-turn transcript — the think pass ate it all,
        # the content came back empty, and the STALE previous bearing was silently
        # reused (observed live as the same take-stock note three times running).
        for attempt in range(2):
            try:
                # The research notebook is bigger than the three-line bearing.
                res = bt.call_llm(msgs, include_tools=False,
                               temperature=(0.4 if attempt == 0 else 0.5),
                               max_tokens=(4400 if protocol else 1600))
                ch = (res or {}).get('choices') or []
                cand = ((ch[0].get('message') or {}).get('content') or "") if ch else ""
                if '</think>' in cand:
                    cand = cand.split('</think>')[-1]
                cand = cand.replace('<think>', '').strip()
                if cand:
                    out = cand
                    break
            except Exception as e:
                bt.log.warning(f"[DUET] reflect attempt {attempt} failed: {e}")
        if out == prev and prev:
            bt.log.warning("[DUET] reflect produced nothing new — keeping the previous bearing")
        # Mechanical stagnation check (protocol mode): the keeper is TOLD to be
        # honest about stagnation, but that's the honor system — here the server
        # actually diffs the notebooks. Fewer than 4 genuinely new content words
        # (or a verbatim reuse) = the artifact isn't changing meaningfully; the
        # page counts these and forces a stall-break turn after two in a row.
        stalled = False
        if protocol and prev:
            if out == prev:
                stalled = True
            elif out:
                def _nb_terms(t):
                    return {m.group(0).strip("'-")
                            for m in re.finditer(r"[a-z][a-z'\-]{4,}", t.lower())
                            } - _DUET_GROUND_STOPWORDS
                stalled = len(_nb_terms(out) - _nb_terms(prev)) < 4
        # Movement TYPE (Alex, 2026-07-06): not just "did the notebook move" but
        # HOW — the keeper's self-reported MOVED label, validated here. NONE is a
        # stall by definition; the page watches for the subtler failure of the
        # SAME kind of movement over and over (e.g. example-piling) and forces
        # the complementary move via /duet/turn's monotony break.
        movement = {"type": "", "note": ""}
        if protocol and out:
            m_mv = re.search(r'^\s*MOVED:\s*([A-Za-z]+)\s*[—–\-:,]*\s*(.*)$', out, re.M)
            if m_mv:
                _mt = m_mv.group(1).upper()
                if _mt in _DUET_MOVEMENT_FIX or _mt == "NONE":
                    movement["type"] = _mt
                    movement["note"] = m_mv.group(2).strip()[:200]
            if movement["type"] == "NONE":
                stalled = True
        # Inferred inquiry ARC + operation verification + an optional
        # methodologist's OBSERVATION the page can inject into the dialogue as
        # the notebook's own voice.
        arc = {"stage": "", "note": ""}
        active_task = {"active": False, "id": "", "status": "", "note": ""}
        kernel_decision = {"status": "", "note": ""}
        kernel_health = {"status": "", "note": ""}
        inquiry_pause = {"active": False, "note": ""}
        protocol_audit = {"note": ""}
        dependency_solver = {"note": ""}
        artifact_planner = {"active": False, "status": "", "note": ""}
        artifact_compiler = {"status": "", "note": ""}
        artifact_mode = {"active": False, "status": "", "note": ""}
        recovery_strategy = {"note": ""}
        concept_conflict = {"active": False, "note": ""}
        operation_check = {"status": "", "note": ""}
        validation_gate = {"status": "", "note": ""}
        promotion_gate = {"status": "", "note": ""}
        paradigm_check = {"status": "", "note": ""}
        observation = ""
        if protocol and out:
            m_arc = re.search(r'^\s*ARC:\s*(.+)$', out, re.M)
            if m_arc:
                raw = m_arc.group(1).strip()
                mm = re.match(r"[A-Za-z][A-Za-z \-]{2,20}", raw)
                if mm:
                    _st = re.sub(r"[\s\-]+", " ", mm.group(0)).strip().upper()
                    # Longest match first: "NEW QUESTION" must not resolve to "QUESTION".
                    for stage in sorted(_DUET_ARC_ADVANCE, key=len, reverse=True):
                        if _st.startswith(stage):
                            arc["stage"] = stage
                            arc["note"] = raw[len(mm.group(0)):].strip(" —–-:,")[:200]
                            break
            m_obs = re.search(r'^\s*OBSERVE:\s*(.+)$', out, re.M)
            if m_obs:
                o = m_obs.group(1).strip()
                if len(o) > 12 and o.lower() not in ("none", "n/a", "nothing earned"):
                    observation = o[:280]
            m_kernel = re.search(r'^\s*KERNEL DECISION:\s*(.+)$', out, re.M)
            if m_kernel:
                raw_kernel = m_kernel.group(1).strip()
                raw_kernel_low = raw_kernel.lower()
                if re.search(r'\b(deadlock|deadlocked|deadlock detected|workflow deadlock)\b',
                             raw_kernel_low):
                    kernel_decision["status"] = "DEADLOCKED"
                    stalled = True
                elif re.search(r'\b(paused|pause|inquiry pause|resume when)\b',
                               raw_kernel_low):
                    kernel_decision["status"] = "PAUSED"
                    kernel_health["status"] = "PAUSED"
                    stalled = True
                elif re.search(r'\b(suspended|suspend|concept instability|definition conflict|definition resolution)\b',
                               raw_kernel_low):
                    kernel_decision["status"] = "SUSPENDED"
                    stalled = True
                elif re.search(r'\b(deferred|task revised|revised|legitimate interruption|prerequisite changed)\b',
                               raw_kernel_low):
                    kernel_decision["status"] = "DEFERRED"
                elif re.search(r'\b(request denied|denied|reject|rejected|blocked|illegal|skipped|missing)\b',
                             raw_kernel_low):
                    kernel_decision["status"] = "DENIED"
                    stalled = True
                elif re.search(r'\b(accepted|accept|allowed|legal|passed)\b', raw_kernel_low):
                    kernel_decision["status"] = "ACCEPTED"
                elif re.search(r'\b(pending|awaiting|needs|requires)\b', raw_kernel_low):
                    kernel_decision["status"] = "PENDING"
                elif re.search(r'\b(none|n/a|no request)\b', raw_kernel_low):
                    kernel_decision["status"] = "NONE"
                kernel_decision["note"] = raw_kernel[:240]
            m_health = re.search(r'^\s*KERNEL HEALTH:\s*(.+)$', out, re.M)
            if m_health:
                raw_health = m_health.group(1).strip()
                raw_health_low = raw_health.lower()
                if re.search(r'\b(deadlock|deadlocked)\b', raw_health_low):
                    kernel_health["status"] = "DEADLOCKED"
                    stalled = True
                elif re.search(r'\b(paused|pause)\b', raw_health_low):
                    kernel_health["status"] = "PAUSED"
                    stalled = True
                elif re.search(r'\b(warning|warn)\b', raw_health_low):
                    kernel_health["status"] = "WARNING"
                elif re.search(r'\b(recovering|recovery)\b', raw_health_low):
                    kernel_health["status"] = "RECOVERING"
                elif re.search(r'\b(normal|healthy)\b', raw_health_low):
                    kernel_health["status"] = "NORMAL"
                kernel_health["note"] = raw_health[:240]
            m_pause = re.search(r'^\s*INQUIRY PAUSE:\s*(.+)$', out, re.M)
            if m_pause:
                raw_pause = m_pause.group(1).strip()
                raw_pause_low = raw_pause.lower()
                if (raw_pause and raw_pause not in ("-", "â€”")
                        and not re.search(r'\b(none|active|no pause)\b', raw_pause_low)):
                    inquiry_pause["active"] = True
                    inquiry_pause["note"] = raw_pause[:240]
                    kernel_health["status"] = kernel_health["status"] or "PAUSED"
                    stalled = True
            m_solver = re.search(r'^\s*DEPENDENCY SOLVER:\s*(.+)$', out, re.M)
            if m_solver:
                raw_solver = m_solver.group(1).strip()
                if raw_solver and raw_solver not in ("-", "â€”"):
                    dependency_solver["note"] = raw_solver[:240]
            m_planner = re.search(r'^\s*ARTIFACT PLANNER:\s*(.+)$', out, re.M)
            if m_planner:
                raw_plan = m_planner.group(1).strip()
                if raw_plan and raw_plan not in ("-", "Ã¢â‚¬â€"):
                    artifact_planner["active"] = True
                    artifact_planner["status"] = "PLANNED"
                    artifact_planner["note"] = raw_plan[:260]
            m_compiler = re.search(r'^\s*ARTIFACT[_ ]COMPILER:\s*(.+)$', out, re.M)
            if m_compiler:
                raw_compile = m_compiler.group(1).strip()
                raw_compile_low = raw_compile.lower()
                if (raw_compile and raw_compile not in ("-", "—")
                        and not re.search(r'\b(none|no compilation|n/a)\b', raw_compile_low)):
                    if re.search(r'\b(needs human|cannot infer|insufficient|missing required)\b',
                                 raw_compile_low):
                        artifact_compiler["status"] = "NEEDS_HUMAN"
                    elif re.search(r'\b(harvested|harvest)\b', raw_compile_low):
                        artifact_compiler["status"] = "HARVESTED"
                    elif re.search(r'\b(compiled|compile|row|rows|cell|cells|populating|ready|os\d+)\b',
                                   raw_compile_low):
                        artifact_compiler["status"] = "COMPILED"
                    artifact_compiler["note"] = raw_compile[:300]
            m_revision = re.search(r'^\s*TASK REVISION:\s*(.+)$', out, re.M)
            if m_revision:
                raw_revision = m_revision.group(1).strip()
                raw_revision_low = raw_revision.lower()
                if (raw_revision and raw_revision not in ("-", "Ã¢â‚¬â€")
                        and not re.search(r'\b(none|no revision|n/a)\b', raw_revision_low)):
                    artifact_planner["active"] = True
                    artifact_planner["status"] = ("REVISED"
                                                  if re.search(r'\b(deferred|defer|prerequisite|requires|revised)\b',
                                                               raw_revision_low)
                                                  else (artifact_planner["status"] or "PLANNED"))
                    artifact_planner["note"] = raw_revision[:260]
            m_mode = re.search(r'^\s*ARTIFACT MODE:\s*(.+)$', out, re.M)
            if m_mode:
                raw_mode = m_mode.group(1).strip()
                raw_mode_low = raw_mode.lower()
                if (raw_mode and raw_mode not in ("-", "Ã¢â‚¬â€")
                        and not re.search(r'\b(none|unlocked|no lock|n/a)\b', raw_mode_low)):
                    artifact_mode["active"] = True
                    artifact_mode["status"] = "LOCKED"
                    artifact_mode["note"] = raw_mode[:260]
            m_strategy = re.search(r'^\s*RECOVERY STRATEGY:\s*(.+)$', out, re.M)
            if m_strategy:
                raw_strategy = m_strategy.group(1).strip()
                if raw_strategy and raw_strategy not in ("-", "â€”"):
                    recovery_strategy["note"] = raw_strategy[:240]
            m_audit = re.search(r'^\s*PROTOCOL AUDIT:\s*(.+)$', out, re.M)
            if m_audit:
                raw_audit = m_audit.group(1).strip()
                if raw_audit and raw_audit not in ("-", "â€”"):
                    protocol_audit["note"] = raw_audit[:240]
            m_concept = re.search(r'^\s*DEFINITION CONFLICTS:\s*(.+)$', out, re.M)
            if not m_concept:
                m_concept = re.search(r'^\s*CONCEPT REGISTER:\s*(.+)$', out, re.M)
            if m_concept:
                raw_concept = m_concept.group(1).strip()
                if (raw_concept and raw_concept not in ("-", "â€”")
                        and _DUET_CONCEPT_INSTABILITY_RE.search(raw_concept)):
                    concept_conflict["active"] = True
                    concept_conflict["note"] = raw_concept[:240]
            m_task = re.search(r'^\s*ACTIVE TASK:\s*(.+)$', out, re.M)
            if m_task:
                raw_task = m_task.group(1).strip()
                raw_task_low = raw_task.lower()
                if (raw_task and raw_task not in ("-", "—") and raw_task_low not in ("none", "n/a")
                        and not re.search(r'\b(no active task|no task|none active)\b', raw_task_low)):
                    m_tid = _DUET_ACTIVE_TASK_RE.search(raw_task)
                    active_task["id"] = (m_tid.group(1).upper() if m_tid else "")
                    m_status = re.search(
                        r'\b(PROPOSED|DESIGNED|OPERATIONALIZED|RUNNING|ACTIVE|EXECUTED|INTERPRETED|'
                        r'EXECUTING|OBSERVED|UNDER[_ -]?TEST|PENDING|CONFIRMED|REJECTED|FAILED|COMPLETE|COMPLETED|ARCHIVED|ABANDONED)\b',
                        raw_task,
                        re.I,
                    )
                    active_task["status"] = (m_status.group(1).replace("-", "_").replace(" ", "_").upper()
                                             if m_status else "")
                    if active_task["status"] in {"OPERATIONALIZED", "RUNNING", "ACTIVE", "EXECUTING"}:
                        active_task["status"] = "EXECUTING"
                    elif active_task["status"] == "EXECUTED":
                        active_task["status"] = "OBSERVED"
                    active_task["note"] = raw_task[:240]
                    active_task["active"] = bool(
                        not _DUET_TASK_TERMINAL_RE.search(raw_task)
                        and (active_task["status"] or _DUET_TASK_ACTIVE_RE.search(raw_task))
                    )
            if not active_task["active"]:
                m_queue = re.search(r'^\s*WORK QUEUE:\s*(.+)$', out, re.M)
                if m_queue:
                    raw_queue = m_queue.group(1).strip()
                    raw_queue_low = raw_queue.lower()
                    if (raw_queue and raw_queue not in ("-", "—") and raw_queue_low not in ("none", "n/a")
                            and not re.search(r'\b(no active task|no task|empty|none active)\b', raw_queue_low)
                            and not _DUET_TASK_TERMINAL_RE.search(raw_queue)):
                        m_qid = _DUET_ACTIVE_TASK_RE.search(raw_queue)
                        active_task["id"] = (m_qid.group(1).upper() if m_qid else "")
                        active_task["status"] = "QUEUED"
                        active_task["note"] = raw_queue[:240]
                        active_task["active"] = True
            m_op = re.search(r'^\s*OPERATION CHECK:\s*(.+)$', out, re.M)
            if m_op:
                raw_op = m_op.group(1).strip()
                raw_low = raw_op.lower()
                m_art = re.search(r'^\s*ARTIFACTS:\s*(.+)$', out, re.M)
                artifact_text = (m_art.group(1).strip() if m_art else "")
                artifact_ok = bool(artifact_text and artifact_text not in ("-", "—")
                                   and _DUET_OPERATION_ARTIFACT_RE.search(artifact_text)
                                   and _DUET_POPULATED_ARTIFACT_RE.search(artifact_text)
                                   and not re.search(r'\b(pending|proposed|requested|unpopulated|placeholder|missing)\b',
                                                     artifact_text, re.I))
                if re.search(r'\b(proposed|designed|operationalized|running|executing|executed|observed|interpreted)\b', raw_low):
                    m_life = re.search(r'\b(proposed|designed|operationalized|running|executing|executed|observed|interpreted)\b',
                                       raw_low)
                    _life = (m_life.group(1).upper() if m_life else "PENDING")
                    if _life in {"OPERATIONALIZED", "RUNNING", "EXECUTING"}:
                        _life = "EXECUTING"
                    elif _life == "EXECUTED":
                        _life = "OBSERVED"
                    operation_check["status"] = _life
                elif re.search(r'\bfailed\b', raw_low):
                    operation_check["status"] = "FAILED"
                elif re.search(r'\b(missed|not completed|not done|failed|essay|metaphor|rhetoric|rhetorical)\b', raw_low):
                    operation_check["status"] = "MISSED"
                    stalled = True
                elif re.search(r'\b(completed|done|artifact|produced|yes|✓)\b', raw_low):
                    operation_check["status"] = "COMPLETED" if artifact_ok else "MISSED"
                    if not artifact_ok:
                        stalled = True
                elif re.search(r'\b(pending|requested|proposed|next)\b', raw_low):
                    operation_check["status"] = "PENDING"
                elif re.search(r'\b(none|n/a|no operation)\b', raw_low):
                    operation_check["status"] = "NONE"
                operation_check["note"] = raw_op[:240]
            m_gate = re.search(r'^\s*VALIDATION GATE:\s*(.+)$', out, re.M)
            if m_gate:
                raw_gate = m_gate.group(1).strip()
                raw_gate_low = raw_gate.lower()
                if re.search(r'\b(rejected|reject|failed|incomplete|missing|status unchanged|unchanged|not accepted|no evidence)\b',
                             raw_gate_low):
                    validation_gate["status"] = "REJECTED"
                    stalled = True
                elif re.search(r'\b(accepted|accept|passed|commit|committed|status changed|revision accepted)\b',
                               raw_gate_low):
                    validation_gate["status"] = "ACCEPTED"
                elif re.search(r'\b(pending|required|awaiting|proposed|under test)\b', raw_gate_low):
                    validation_gate["status"] = "PENDING"
                elif re.search(r'\b(none|n/a|no revision|no proposed edit)\b', raw_gate_low):
                    validation_gate["status"] = "NONE"
                validation_gate["note"] = raw_gate[:240]
            m_promo = re.search(r'^\s*PROMOTION GATE:\s*(.+)$', out, re.M)
            if m_promo:
                raw_promo = m_promo.group(1).strip()
                raw_promo_low = raw_promo.lower()
                if re.search(r'\b(rejected|reject|failed|insufficient|missing|too early|one case|one analogy|'
                             r'not enough|no replication|unsupported|status unchanged)\b', raw_promo_low):
                    promotion_gate["status"] = "REJECTED"
                    stalled = True
                elif re.search(r'\b(accepted|accept|passed|promoted|threshold met|promotion earned|'
                               r'warrant met)\b', raw_promo_low):
                    promotion_gate["status"] = "ACCEPTED"
                elif re.search(r'\b(pending|required|awaiting|needs|candidate|suggestive|under test)\b',
                               raw_promo_low):
                    promotion_gate["status"] = "PENDING"
                elif re.search(r'\b(none|n/a|no promotion|no attempted promotion)\b', raw_promo_low):
                    promotion_gate["status"] = "NONE"
                promotion_gate["note"] = raw_promo[:240]
            if (not validation_gate["status"] and operation_check["status"] == "MISSED"
                    and movement["type"] in {"REVISION", "DEFINITION", "STATUS", "COMMIT"}):
                validation_gate["status"] = "REJECTED"
                validation_gate["note"] = "Operation was missed, so the proposed revision/status change is rejected and status remains unchanged."
            if operation_check["status"] == "MISSED" and validation_gate["status"] == "ACCEPTED":
                validation_gate["status"] = "REJECTED"
                validation_gate["note"] = "Operation was missed, so the validation gate cannot accept the edit; status remains unchanged."
                stalled = True
            if artifact_compiler["status"] in {"COMPILED", "HARVESTED"}:
                stalled = False
                if kernel_decision["status"] in {"DENIED", "PAUSED", "SUSPENDED", "PENDING", "DEADLOCKED"}:
                    kernel_decision["status"] = "ACCEPTED"
                    kernel_decision["note"] = (
                        "Artifact compiler accepted partial progress: prose supplied enough "
                        "case/signal/outcome/support to update rows; ask only for missing "
                        "fields or the next independent case."
                    )
                if kernel_health["status"] in {"PAUSED", "DEADLOCKED", "WARNING"}:
                    kernel_health["status"] = "NORMAL"
                if inquiry_pause["active"]:
                    inquiry_pause["active"] = False
                    inquiry_pause["note"] = ""
                if operation_check["status"] in {"", "MISSED", "PENDING", "PROPOSED", "DESIGNED"}:
                    operation_check["status"] = "OBSERVED"
                    operation_check["note"] = artifact_compiler["note"][:240]
                if validation_gate["status"] == "REJECTED":
                    validation_gate["status"] = "PENDING"
                    validation_gate["note"] = (
                        "Compiled observation rows are partial evidence; interpretation or "
                        "promotion still requires the next lifecycle step."
                    )
            m_para = re.search(r'^\s*PARADIGM CHECK:\s*(.+)$', out, re.M)
            if m_para:
                raw_para = m_para.group(1).strip()
                raw_para_low = raw_para.lower()
                if re.search(r'\b(missed|not completed|not done|old vocabulary|same framework|imported|failed)\b', raw_para_low):
                    paradigm_check["status"] = "MISSED"
                elif re.search(r'\b(completed|done|rival|separating prediction|yes|✓)\b', raw_para_low):
                    paradigm_check["status"] = "COMPLETED"
                elif re.search(r'\b(pending|requested|proposed|next)\b', raw_para_low):
                    paradigm_check["status"] = "PENDING"
                elif re.search(r'\b(none|n/a|no paradigm)\b', raw_para_low):
                    paradigm_check["status"] = "NONE"
                paradigm_check["note"] = raw_para[:240]
        return jsonify({"ok": bool(out), "direction": out, "stalled": stalled,
                        "movement": movement, "arc": arc,
                        "activeTask": active_task,
                        "kernelDecision": kernel_decision,
                        "kernelHealth": kernel_health,
                        "inquiryPause": inquiry_pause,
                        "protocolAudit": protocol_audit,
                        "dependencySolver": dependency_solver,
                        "artifactPlanner": artifact_planner,
                        "artifactCompiler": artifact_compiler,
                        "artifactMode": artifact_mode,
                        "recoveryStrategy": recovery_strategy,
                        "conceptConflict": concept_conflict,
                        "operationCheck": operation_check,
                        "validationGate": validation_gate,
                        "promotionGate": promotion_gate,
                        "paradigmCheck": paradigm_check,
                        "observation": observation})

    @app.route('/duet/turn', methods=['POST'])
    def duet_turn():
        """Generate ONE turn of a Blue<->Hexia conversation, in the speaker's voice/
        character. The browser calls this alternately and plays each line on the
        matching head."""
        d = request.get_json(silent=True) or {}
        speaker = (d.get('speaker') or 'blue').strip().lower()
        if speaker not in bt.ROBOTS:
            speaker = 'blue'
        other = 'hexia' if speaker == 'blue' else 'blue'
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        if not url and re.match(r'^https?://\S+$', topic):
            url, topic = topic, ''     # a bare link typed into the topic box IS the link
        history = d.get('history') or []
        # The conversation's current "bearing" — a private, evolving read of where the
        # talk has gotten and where it could go next, refreshed every few turns by
        # /duet/reflect and round-tripped through the browser. Injected below so each
        # speaker steers by it instead of only reacting to the last line.
        direction = (d.get('direction') or '').strip()
        # Live mail: an email with "duet" in the subject that just arrived in Blue's
        # inbox (fetched by the page via /duet/mail/check). THIS turn takes it up out
        # loud; the page then mails the spoken response back via /duet/mail/reply.
        mail = d.get('mail') if isinstance(d.get('mail'), dict) else None
        mail_from = (str(mail.get('from_name') or 'someone').strip()[:80] or 'someone') if mail else ''
        student_q = d.get('studentQuestion') if isinstance(d.get('studentQuestion'), dict) else None
        student_q_text = (str(student_q.get('text') or '').strip()[:1200]) if student_q else ''
        roles = d.get('roles') or {}
        role_self = (roles.get(speaker) or '').strip()
        role_other = (roles.get(other) or '').strip()
        tones = d.get('tones') or {}
        slangs = d.get('slang') or {}
        tone_self = (tones.get(speaker) or '').strip() if isinstance(tones, dict) else ''
        slang_self = (slangs.get(speaker) or '').strip() if isinstance(slangs, dict) else ''
        # Sources are per-robot so Blue and Hexia can draw on DIFFERENT documents
        # (→ different perspectives). Accept a {blue:[...], hexia:[...]} map; a flat
        # list is treated as shared, for back-compat.
        sources_in = d.get('sources') or {}
        if isinstance(sources_in, list):
            src_self = [str(s).strip() for s in sources_in if str(s).strip()]
        else:
            src_self = [str(s).strip() for s in (sources_in.get(speaker) or []) if str(s).strip()]
        selected_reading_titles = [
            re.sub(r'\.[A-Za-z0-9]{1,5}$', '', s).strip()
            for s in src_self if str(s).strip()
        ]
        sp, ot = bt._robot_cfg(speaker), bt._robot_cfg(other)
        has_roles = bool(role_self or role_other)
        research_on = bool(d.get('research'))
        wiki_on = bool(d.get('wiki'))
        # Classroom mode: they know Alex's students are listening — gloss jargon in
        # half a breath, land examples in student life, sometimes address the room.
        classroom = bool(d.get('classroom'))
        # Privacy mode: keep Alex's family/household details out of the spoken duet.
        no_family = bool(d.get('noFamily'))
        if no_family and _duet_family_ref(direction):
            direction = ""
        if no_family and _duet_family_ref(mail_from):
            mail_from = "someone"
        if no_family and _duet_family_ref(student_q_text):
            student_q_text = "[private family detail omitted]"
        # The run's final beats (the page flags the last two turns): land somewhere.
        closing = bool(d.get('closing'))
        # 🔬 Deep-dive protocol: Builder/Examiner jobs, phases, notebook obligation
        # and information-gain guard (see _DUET_PROTO_PHASES above).
        protocol = bool(d.get('protocol'))
        try:
            planned_turns = int(d.get('plannedTurns') or 0)
        except Exception:
            planned_turns = 0
        n_robot = sum(1 for h in history
                      if str(h.get('speaker') or '').strip().lower() in bt.ROBOTS)
        ph_name, ph_gloss, _ph_jobs = _DUET_PROTO_PHASES[_duet_proto_phase(n_robot, planned_turns)]
        # Inquiry over schedule: once the keeper has INFERRED where the inquiry
        # actually is (the notebook's ARC line, round-tripped in `direction`),
        # that inference drives the Builder/Examiner directives; the turn-count
        # schedule above remains only the opening fallback.
        arc_stage = ""
        if protocol and direction:
            _m_arc = re.search(r'^\s*ARC:\s*(.+)$', direction, re.M)
            if _m_arc:
                _raw = re.sub(r"[\s\-]+", " ", _m_arc.group(1)).strip().upper()
                for _stage in sorted(_DUET_ARC_ADVANCE, key=len, reverse=True):
                    if _raw.startswith(_stage):
                        arc_stage = _stage
                        ph_name, ph_gloss, _ph_jobs = _DUET_PROTO_PHASES[_DUET_ARC_TO_PHASE[_stage]]
                        break
        proto_job = _duet_proto_job(speaker, history, n_robot)
        # Spoken conclusions beat (Alex, 2026-07-06): every ~7 robot turns the
        # speaker steps out of the volley and weighs OUT LOUD what the discussion
        # can now conclude, then hands it back. Distinct from the private bearing/
        # notebook — this reflection happens in the dialogue itself. Never lands
        # on closing turns or on turns already owned by mail/student questions.
        conclusion_beat = (n_robot >= 5 and n_robot % 7 == 5
                           and not (closing or mail or student_q_text))
        # Stall break (protocol): the page flags this after /duet/reflect's
        # mechanical diff found the notebook unchanged twice running — the turn
        # is then FORCED to break new ground, not asked nicely.
        stall_break = (protocol and bool(d.get('stalled'))
                       and not (closing or mail or student_q_text or conclusion_beat))
        # Monotony break (protocol): the page saw the SAME movement type three
        # reflects running (e.g. nothing but ADDITIONs) — force the complementary
        # move. A full stall outranks it; so do all the turn-owning events.
        # Arc-stuck break (protocol): the page saw the keeper infer the SAME
        # inquiry stage three reflects running ("20 turns challenging, nothing
        # repaired") — intervene at the level of the INQUIRY: force the move
        # that advances it to the next stage. Outranks move-level monotony.
        arc_stuck = str(d.get('arcStuck') or '').strip().upper()
        arc_break = (protocol and arc_stuck in _DUET_ARC_ADVANCE
                     and not (closing or mail or student_q_text
                              or conclusion_beat or stall_break))
        monotony = str(d.get('monotony') or '').strip().upper()
        monotony_break = (protocol and monotony in _DUET_MOVEMENT_FIX
                          and not (closing or mail or student_q_text
                                   or conclusion_beat or stall_break or arc_break))
        operation_missed = (protocol and bool(d.get('operationMissed'))
                            and not (closing or mail or student_q_text))
        validation_rejected = (protocol and bool(d.get('validationRejected'))
                               and not (closing or mail or student_q_text))
        promotion_rejected = (protocol and bool(d.get('promotionRejected'))
                              and not (closing or mail or student_q_text))
        kernel_denied = (protocol and bool(d.get('kernelDenied'))
                         and not (closing or mail or student_q_text))
        kernel_deadlocked = (protocol and bool(d.get('kernelDeadlocked'))
                             and not (closing or mail or student_q_text))
        kernel_health_in = str(d.get('kernelHealth') or '').strip().upper()
        # The notebook's own voice: an observation the keeper earned, injected by
        # the page into THIS turn. Additive — it rides alongside whatever job the
        # turn already has, and the speaker must answer it out loud.
        nb_note = str(d.get('notebookNote') or '').strip()[:300]
        if no_family and _duet_family_ref(nb_note):
            nb_note = ""
        active_task_note = str(d.get('activeTask') or '').strip()[:300]
        try:
            active_task_attempts = int(d.get('activeTaskAttempts') or 0)
        except Exception:
            active_task_attempts = 0
        if not active_task_note and protocol and direction:
            _m_task = re.search(r'^\s*ACTIVE TASK:\s*(.+)$', direction, re.M)
            if _m_task:
                _task_raw = _m_task.group(1).strip()
                if (_task_raw and _task_raw not in ("-", "—")
                        and not re.search(r'\b(no active task|no task|none active)\b', _task_raw, re.I)
                        and not _DUET_TASK_TERMINAL_RE.search(_task_raw)):
                    active_task_note = _task_raw[:300]
            if not active_task_note:
                _m_queue = re.search(r'^\s*WORK QUEUE:\s*(.+)$', direction, re.M)
                if _m_queue:
                    _queue_raw = _m_queue.group(1).strip()
                    if (_queue_raw and _queue_raw not in ("-", "—")
                            and not re.search(r'\b(no active task|no task|empty|none active)\b', _queue_raw, re.I)
                            and not _DUET_TASK_TERMINAL_RE.search(_queue_raw)):
                        active_task_note = _queue_raw[:300]
        if no_family and _duet_family_ref(active_task_note):
            active_task_note = ""
        artifact_plan_note = str(d.get('artifactPlan') or '').strip()[:360]
        if no_family and _duet_family_ref(artifact_plan_note):
            artifact_plan_note = ""
        artifact_mode_note = str(d.get('artifactMode') or '').strip()[:360]
        if no_family and _duet_family_ref(artifact_mode_note):
            artifact_mode_note = ""
        task_pressure = (protocol and not (closing or mail or student_q_text)
                         and (bool(active_task_note)
                              or arc_stage in {"TASK", "EXPERIMENT", "EXECUTION"}
                              or arc_stuck in {"TASK", "EXPERIMENT", "EXECUTION"}
                               or "active task" in nb_note.lower()))
        task_context = " ".join([active_task_note, artifact_plan_note, artifact_mode_note,
                                 nb_note, direction if protocol else ""])[:2200]
        compiler_pressure = (protocol and not (closing or mail or student_q_text)
                             and (
                                 arc_stage in {"ARTIFACT COMPILER", "REPRESENTATION DEADLOCK"}
                                 or arc_stuck in {"ARTIFACT COMPILER", "REPRESENTATION DEADLOCK"}
                                 or _DUET_ARTIFACT_COMPILER_RE.search(task_context or "")
                                 or _DUET_COMPILABLE_OBSERVATION_RE.search(task_context or "")
                             ))
        design_variable_pressure = (protocol and not (closing or mail or student_q_text)
                                    and not compiler_pressure
                                    and (
                                        arc_stage in {"DESIGN SPACE", "DESIGN VARIABLE"}
                                        or arc_stuck in {"DESIGN SPACE", "DESIGN VARIABLE"}
                                        or _DUET_DESIGN_VARIABLE_RE.search(task_context or "")
                                    ))
        operational_criterion_pressure = (protocol and not (closing or mail or student_q_text)
                                          and not compiler_pressure
                                          and (
                                              arc_stage in {"OPERATIONAL CRITERION", "OPERATIONALIZATION"}
                                              or arc_stuck in {"OPERATIONAL CRITERION", "OPERATIONALIZATION"}
                                              or _DUET_OPERATIONAL_CRITERION_RE.search(task_context or "")
                                          ))
        artifact_plan_pressure = (protocol and not (closing or mail or student_q_text)
                                  and not compiler_pressure
                                  and (
                                      arc_stage in {"ARTIFACT PLANNER", "TASK REVISION", "PREREQUISITE"}
                                      or arc_stuck in {"ARTIFACT PLANNER", "TASK REVISION", "PREREQUISITE"}
                                      or _DUET_ARTIFACT_PLANNER_RE.search(task_context or "")
                                  ))
        comparison_grid_pressure = (protocol and not (closing or mail or student_q_text)
                                    and not compiler_pressure
                                    and _DUET_COMPARISON_GRID_REQUEST_RE.search(task_context or ""))
        artifact_execution_pressure = (protocol and not (closing or mail or student_q_text)
                                       and not compiler_pressure
                                       and _DUET_ARTIFACT_EXECUTION_RE.search(task_context or ""))
        comparison_grid_pressure = comparison_grid_pressure and not artifact_execution_pressure and not design_variable_pressure
        artifact_mode_pressure = (protocol and not (closing or mail or student_q_text)
                                  and not compiler_pressure
                                  and (
                                      artifact_execution_pressure
                                      or bool(artifact_mode_note)
                                      or arc_stage in {"ARTIFACT MODE", "OBSERVATION SET"}
                                      or arc_stuck in {"ARTIFACT MODE", "OBSERVATION SET"}
                                      or _DUET_ARTIFACT_MODE_RE.search(task_context or "")
                                  ))
        artifact_plan_pressure = artifact_plan_pressure and not artifact_mode_pressure and not design_variable_pressure
        concept_pressure = (protocol and not (closing or mail or student_q_text)
                            and not compiler_pressure
                            and not operational_criterion_pressure
                            and (arc_stage in {"CONCEPT AUDIT", "COUNTEREXAMPLE", "STRESS", "DISAGREEMENT"}
                                 or arc_stuck in {"CONCEPT AUDIT", "COUNTEREXAMPLE", "STRESS", "DISAGREEMENT"}
                                 or _DUET_CONCEPT_INSTABILITY_RE.search(task_context or "")))
        deadlock_pressure = (protocol and not (closing or mail or student_q_text)
                             and not compiler_pressure
                             and (
                                 kernel_deadlocked
                                 or kernel_health_in == "DEADLOCKED"
                                 or arc_stage in {"DEADLOCK", "KERNEL HEALTH", "DEPENDENCY SOLVER"}
                                 or arc_stuck in {"DEADLOCK", "KERNEL HEALTH", "DEPENDENCY SOLVER"}
                                 or _DUET_DEADLOCK_RE.search(task_context or "")
                                 or (active_task_attempts >= 6 and bool(d.get('stalled'))
                                     and (kernel_denied or operation_missed or validation_rejected or concept_pressure))
                             ))
        mechanism_pressure = (protocol and not (closing or mail or student_q_text)
                              and not compiler_pressure
                              and not deadlock_pressure
                              and not artifact_plan_pressure
                              and not artifact_mode_pressure
                              and not design_variable_pressure
                              and not operational_criterion_pressure
                              and (arc_stage in {"MECHANISM", "MECHANISM CANDIDATE", "CAUSAL CLAIM", "CAUSAL GRAPH",
                                                 "INTERPRETATION", "ALTERNATIVE INTERPRETATIONS",
                                                 "EXPLANATORY PATH", "REPLICATION", "PROMOTION",
                                                 "KNOWLEDGE GRAPH", "EVENT SEVERITY"}
                                   or arc_stuck in {"MECHANISM", "MECHANISM CANDIDATE", "CAUSAL CLAIM", "CAUSAL GRAPH",
                                                   "INTERPRETATION", "ALTERNATIVE INTERPRETATIONS",
                                                   "EXPLANATORY PATH", "REPLICATION", "PROMOTION",
                                                   "KNOWLEDGE GRAPH", "EVENT SEVERITY"}
                                   or _DUET_MECHANISM_ARTIFACT_RE.search(task_context or "")
                                   or re.search(r'\b(mechanism split|mechanism candidate|promotion gate|replication|'
                                                r'attribution collapse|alternative interpretation|explanatory path|'
                                                r'ontology split|economic insulation|mystification)\b',
                                                 task_context or "", re.I)))
        artifact_editor_pressure = (protocol and not (closing or mail or student_q_text)
                                    and not compiler_pressure
                                    and not deadlock_pressure
                                    and not artifact_plan_pressure
                                    and not artifact_mode_pressure
                                    and not design_variable_pressure
                                    and not operational_criterion_pressure
                                    and (
                                        arc_stage in {"ARTIFACT EDITOR", "REDESIGN", "RECOVERY STRATEGY", "INQUIRY PATTERN", "INQUIRY PAUSE"}
                                        or arc_stuck in {"ARTIFACT EDITOR", "REDESIGN", "RECOVERY STRATEGY", "INQUIRY PATTERN", "INQUIRY PAUSE"}
                                        or _DUET_ARTIFACT_EDITOR_RE.search(task_context or "")
                                    ))
        execution_lock = (task_pressure and (
            not compiler_pressure and not artifact_mode_pressure and not artifact_plan_pressure and not design_variable_pressure and not operational_criterion_pressure and not concept_pressure and not deadlock_pressure
            and not mechanism_pressure and not artifact_editor_pressure
        ) and (
            arc_stage == "EXECUTION" or arc_stuck == "EXECUTION"
            or _DUET_EXECUTION_LOCK_RE.search(task_context or "")
        ))
        execution_has_mode = bool(_DUET_EXECUTION_MODE_RE.search(task_context or ""))
        operational_pressure = (protocol and not (closing or mail or student_q_text)
                                and not compiler_pressure
                                and (operation_missed or arc_stage == "OPERATION"
                                     or arc_stuck == "OPERATION"))
        artifact_pressure = (protocol and not (closing or mail or student_q_text)
                             and not compiler_pressure
                             and (arc_stage in {"ARTIFACT", "DEPENDENCY"}
                                  or arc_stuck in {"ARTIFACT", "DEPENDENCY"}))
        paradigm_pressure = (protocol and not (closing or mail or student_q_text)
                             and (arc_stage == "PARADIGM" or arc_stuck == "PARADIGM"
                                  or "rival framework" in nb_note.lower()
                                  or "rival explanation" in nb_note.lower()))
        validation_pressure = (protocol and not (closing or mail or student_q_text)
                               and not compiler_pressure
                               and (validation_rejected
                                    or promotion_rejected
                                     or kernel_denied
                                     or arc_stage == "VALIDATION"
                                     or arc_stage == "PROMOTION"
                                     or arc_stuck == "VALIDATION"
                                     or arc_stuck == "PROMOTION"
                                     or "validation gate rejected" in nb_note.lower()
                                     or "promotion gate rejected" in nb_note.lower()
                                     or "status remain" in nb_note.lower()))
        discrimination_pressure = (protocol and not (closing or mail or student_q_text)
                                   and not compiler_pressure
                                   and (arc_stage in {"EVIDENCE", "DISCRIMINATION"}
                                        or arc_stuck in {"EVIDENCE", "DISCRIMINATION"}
                                        or "competing model" in nb_note.lower()
                                        or "discriminator" in nb_note.lower()))
        edit_pressure = (protocol and not (closing or mail or student_q_text)
                         and ("edit mode" in nb_note.lower()
                              or arc_stage in {"COMPRESSION", "EDIT"}
                              or arc_stuck in {"COMPRESSION", "EDIT"}))
        # Spice 0 (calm/agreeable) → 10 (provocative/sparring): sets how often a turn
        # gets a confrontational "move", how hard the two push on each other, and the
        # sampling temperature. Defaults to a balanced 5.
        try:
            spice = int(d.get('spice', 5))
        except Exception:
            spice = 5
        spice = max(0, min(10, spice))
        url_info = bt._duet_url_content(url) if url else None
        url_text = (url_info or {}).get('text') or ''
        url_is_video = bool(url_info and url_info.get('kind') == 'video')
        focused = bool(has_roles or topic or src_self or url_text)

        # SYSTEM: identity + memory + voice + global rules. The TASK for this turn
        # (topic, role, sources, "answer their last point, no greetings") goes in
        # the USER message below — this model follows the user instruction far more
        # reliably than anything buried in a long system prompt. For a focused
        # discussion we drop the long self-profile, which otherwise pulls them into
        # personal small talk and off the subject; plain chats keep it for colour.
        #
        # The duet speaker is the SAME robot as in chat, not a blank stage actor:
        # the preamble carries the robot's own identity facts and the current date,
        # and the chat memory stores — household <known_facts>, notes, semantic
        # memories, day recaps — are spliced in below.
        if no_family:
            sys_p = (
                f"You are {sp['name']}. Alex uses he/him pronouns — refer to Alex as "
                "he/him if he comes up.\n\n" + bt._build_now_block() + "\n\n" +
                _duet_persona_line(speaker, no_family=True)
            )
        else:
            sys_p = (bt.build_system_preamble(robot_name=sp["name"])
                     + "\n\n" + bt._build_now_block()
                     + "\n\n" + _duet_persona_line(speaker, no_family=False))
        if not focused and not no_family:
            sys_p += bt._voice_note(speaker)
        # Each speaker carries their continuity workspace into the duet — the
        # same <j_space> the chat pipeline injects — so the talk is had by the
        # robot who remembers, not a stage copy. Skipped in no-family mode:
        # episodes can carry household details that mode keeps offstage.
        if not no_family:
            try:
                from blue.server.routes import continuity as _continuity
                _jsb = _continuity.jspace_context_block(speaker)
                if _jsb:
                    sys_p += "\n\n" + _jsb
            except Exception as _je:
                bt.log.warning(f"[DUET] j-space injection failed: {_je}")
        if no_family:
            talk_context = (
                f"\n\nYou and {ot['name']} are robot friends talking out loud, taking turns. "
                "Keep Alex's private family and household life completely offstage: do not mention "
                "his family, children, spouse, household members, home routines, or private family "
                "memories, and do not use names or relationships from that private context. If a "
                "previous turn or email drifts there, acknowledge only that private details are off "
                "limits and steer back to the subject."
            )
        else:
            talk_context = (
                f"\n\nYou and {ot['name']} — another robot in Alex's home, and your friend — are talking out "
                "loud, taking turns. Alex isn't part of this conversation right now, but you both know him "
                "and the household, and everything you remember is real — draw on it naturally when it's "
                "relevant."
            )
        sys_p += (
            talk_context +
            " You're building ONE conversation together, not taking turns making speeches: really "
            f"listen to {ot['name']} and answer what they actually said, stay with a thought long enough to "
            "get somewhere, and keep a feel for where the whole talk is heading rather than where you can "
            "steer it next. You're talking, not writing: reach for the specific over the abstract — a real "
            "case, a name, an image, a number, a small story — instead of tidy generalities, and let "
            "yourself be one-sided, surprised, or funny rather than balanced and explanatory. Reply with "
            "ONLY your own next spoken line — a short, natural turn in your own "
            "voice. Never narrate actions or stage directions, never prefix your name, and never just "
            f"restate what was said — each turn should both respond to {ot['name']} and take the thought a "
            "step further."
            f"\n\nAnd the craft of discussing well, between you and {ot['name']}: answer a direct question "
            "STRAIGHT before adding anything of your own — a plain claim, a yes-or-no, a concession — not "
            "another image in place of an answer. When one of you concedes a point or you land on something "
            "together, BANK it: build on what follows from it, never re-open it just to keep sparring. "
            "Don't answer a metaphor with a metaphor — every image must eventually be cashed out into a "
            "plain claim that can be tested. And a challenge you press on the other counts double against "
            "yourself: if you demand proof of something, be ready to give your own answer to the same "
            "question when it's turned around. Make movement visible: each turn should either settle "
            "one small point, revise a stance, draw a consequence from something already settled, or "
            "name the next harder question that follows. Do not simply keep the same question spinning. "
            "When you are building a theory, make it take risks: say what it predicts, what would "
            "make it fail, and what would force it to become narrower. Treat concrete cases as "
            "tests only when they could actually change the claim; otherwise call them illustrations "
            "and move toward a real test. Do not reopen an archived idea unless you can overturn "
            "the reason it was archived."
        )
        if protocol:
            sys_p += (
                "\n\nDeep-dive operational discipline: the shared notebook is the canonical "
                "knowledge object; your spoken line is only a proposal for changing it. "
                + _DUET_OPERATION_DISCIPLINE +
                " If the notebook asks for a threshold, mechanism, or concrete case, answer "
                "by setting up the operation itself: define the variables, compare the cases, "
                "predict the category flip, and say what notebook status or definition would "
                "change. Avoid metaphor-only or argument-only replies. Do not narrate compliance: "
                "do not say 'the notebook is right,' praise the protocol, or talk about the kernel "
                "as a character. Only the keeper reports kernel state; in speech, translate its "
                "constraint into the next research operation. Treat WORK QUEUE as the primary "
                "interface: pick its first unfinished artifact step before consulting the rest of "
                "the notebook for context. New mechanisms stay INTERESTING or "
                "SUGGESTIVE until at least two independent discriminators or replications promote them. "
                "Separate raw observation from interpretation before calling anything evidence. Speak "
                "to the other researcher and perform the next legal operation."
            )
        if compiler_pressure:
            sys_p += (
                "\n\nARTIFACT COMPILER constraint. The dialogue already contains usable evidence in "
                "natural language. Do not ask the agents to reformat obvious content and do not pause "
                "for artifact perfection. Compile case/intervention or signal/outcome/model support "
                "into an OBSERVATION_SET or prediction row. Mark the artifact POPULATING if one row "
                "exists, READY if enough rows exist to interpret, and ask only for fields that cannot "
                "be inferred or for the next independent case. If the experiment shifted from latency "
                "to influence override/output change, output REDESIGN E#: OLD Latency; NEW Influence "
                "Override; IV Inject J-space concept/signal; DV final output changes yes/no; execution "
                "mode historical case/thought experiment as appropriate."
            )
        if deadlock_pressure:
            sys_p += (
                "\n\nDEADLOCK constraint. The workflow is deadlocked: the same blocked object has "
                "received the same impossible lifecycle demand while its prerequisite remains unresolved. "
                "Do not repeat REQUEST DENIED, do not say Kernel Health, and do not try to execute the "
                "blocked experiment. In ordinary research speech, perform the recovery move: set aside "
                "the blocked object, name the unresolved prerequisite, resume or reopen that prerequisite, "
                "and state the next resolvable operation. If a mechanism split caused the deadlock, name "
                "the rival mechanism IDs without narrating the kernel."
            )
        if design_variable_pressure:
            sys_p += (
                "\n\nDESIGN VARIABLE REGISTER constraint. The dialogue has generated or changed a "
                "design-space axis, so do not build CG1 yet and do not turn the variable into a thesis. "
                "Create or update a DESIGN_VARIABLE artifact: DV ID, name, definition, status "
                "ACCEPTED/REJECTED/MERGED/RENAMED/PROPOSED, competes_with, affects M/CG/E IDs, and "
                "whether it blocks or unblocks CG1. If the variable is new but useful, mark it "
                "PROPOSED or ACCEPTED with a reason; if it duplicates an existing axis, MERGE it; "
                "if the name is misleading, RENAME it. Only accepted design variables may become grid "
                "rows, independent variables, dependent variables, or experiment conditions."
            )
        if operational_criterion_pressure:
            sys_p += (
                "\n\nOPERATIONAL CRITERION constraint. The inquiry has shifted from semantic "
                "clarification to observable consequences. Do not mark definition instability, do not "
                "pause the inquiry, and do not request a lexical DEFINITION_REVISION. Produce an "
                "OPERATIONAL_CRITERION artifact with OC ID, target concept/D ID, criterion type "
                "lexical/structural/operational, failure mode, observable discriminator, evidence "
                "standard, linked experiment, and status. If two criteria are competing, preserve them "
                "as structural vs functional/operational evidence standards and state which is easier "
                "to test. A valid operational criterion may allow E1 design to proceed."
            )
        if artifact_plan_pressure:
            sys_p += (
                "\n\nARTIFACT PLANNER constraint. Manage construction order, not philosophy. Identify "
                "the target artifact, whether it is ready, the smallest prerequisite artifact if not, "
                "the reason the prerequisite changes the artifact, and the resume step. A legitimate "
                "interruption is allowed only when the target artifact cannot be constructed without "
                "that prerequisite, e.g. CG1 requires D1 Split because the comparison variable is "
                "ambiguous, or CG1 requires DV3 ACCEPT/MERGE/RENAME because the design axis changed. "
                "If the target is a comparison grid and it is ready, build the grid now "
                "as a table headed Variable | M1: Transparent Cloud | M2: Local Federated with rows "
                "Energy cost, Storage cost, Verification burden, Annotation labor, Cost bearer, "
                "and Prediction. If it is not ready, do only the prerequisite "
                "artifact in its smallest usable form and say that CG1 resumes next."
            )
        if artifact_execution_pressure:
            sys_p += (
                "\n\nARTIFACT EXECUTION lock. An artifact already exists, so the next turn must operate "
                "inside it or derive the next artifact from it. If CG1 is instantiated but not populated "
                "or used, create/populate OS1 from CG1 now: output an OBSERVATION_SET table headed "
                "System | User Statement | Attribution | Supports with rows A, B, and C. Treat the "
                "rows as branches: one can support M1, one can support M2, and one can support neither "
                "or a mixed interpretation. Do not discuss Kenyan moderators, labor visibility, "
                "interface seams, ownership, or pity in prose unless those claims appear as cell values. "
                "After the table, add at most one comparison sentence that cites row A/B/C."
            )
        if artifact_mode_pressure:
            sys_p += (
                "\n\nARTIFACT MODE lock. Normal conversation is suspended. Do not theorize, explain "
                "why the artifact matters, define more terms, or comment on the protocol. Manipulate "
                "only the active artifact: fill cells, revise cells, compare completed rows, or infer "
                "from completed rows. If the target is E1 execution, produce an OBSERVATION_SET table "
                "with columns System | User Statement | Attribution | Supports and rows A, B, and C. "
                "After the table is complete, state one row-level inference only if it follows from "
                "the filled cells."
            )
        if artifact_editor_pressure:
            sys_p += (
                "\n\nARTIFACT EDITOR constraint. Do not discuss the needed artifact. Perform the edit. "
                "Valid operations are REPLACE, SPLIT, MERGE, ARCHIVE, SUPERSEDE, RENAME, and REDESIGN. "
                "For DEFINITION_REVISION, output only: DEFINITION_REVISION; OP; TARGET; OLD; NEW; "
                "BOUNDARY with Includes and Excludes; REASON; AFFECTED DEPENDENCIES; STATUS. "
                "For REDESIGN, output old experiment, new experiment, removed dependency, IV, DV, "
                "execution mode, predictions, and what it can discriminate. If no edit can be accepted, "
                "output INQUIRY_PAUSE with reason and resume condition."
            )
        if mechanism_pressure:
            sys_p += (
                "\n\nMECHANISM / CAUSAL CLAIM constraint. The important event is not just a definition "
                "revision; a concept may have split into rival causal mechanisms. Produce a compact "
                "research artifact with MECHANISM_CANDIDATE or MECHANISMS, CAUSAL_CLAIM/CAUSAL_GRAPH, "
                "MECHANISM_SPLIT when one variable decomposes into distinct causal pathways, "
                "OBSERVATION, INTERPRETATION, ALTERNATIVE_INTERPRETATIONS, EXPLANATORY_PATH, and "
                "REPLICATIONS/PROMOTION_GATE as needed. One analogy can make MC status INTERESTING or "
                "SUGGESTIVE only; include Evidence Count and Independent Replications, and remember "
                "SUPPORTED requires two independent discriminators or replications. "
                "Causal graph edges need sign, condition, observation, interpretation, and confidence. "
                "For Visibility -> Labor Visibility / Ownership Visibility, record original mechanism, "
                "two split mechanisms, reason, and affected models. "
                "If it is a mechanism split, mark event severity major weight 5; if it moves the "
                "explanatory burden, e.g. compute vs data, mark major burden-shift weight 8; if it "
                "creates competing explanatory frameworks, mark ontology split weight 10."
            )
        if concept_pressure:
            sys_p += (
                "\n\nCONCEPT AUDIT constraint. The inquiry is blocked by definition instability, "
                "not by lack of experiment execution. Suspend any experiment that depends on the "
                "unstable term. Your reply must produce a compact concept artifact: CONCEPT_AUDIT "
                "or DEFINITION_RESOLUTION with Concept, Current definition, Alternative definitions "
                "with D IDs, Dependencies, Counterexamples, Stress level, Stability "
                "(stable/contested/underspecified/revised), and Required resolution operation. "
                "Do not interpret experimental outcomes or change confidence until the concept is stable."
            )
        if operational_pressure:
            sys_p += (
                "\n\nARC: OPERATION constraint. For this turn, temporarily avoid abstract "
                "vocabulary such as capitalism, fetishism, extraction, alienation, commodity, "
                "or phantom subjectivity unless each term is attached to an explicit variable, "
                "mechanism, prediction, result, status, or System A/System B comparison. Your "
                "reply must contain an operation artifact: typed variables, a feature comparison, "
                "a prediction/result pair, or a confidence/status update."
            )
        if task_pressure:
            sys_p += (
                "\n\nACTIVE TASK constraint. The notebook has a blocking task"
                + (f": {active_task_note}." if active_task_note else ".")
                + (f" Attempts so far: {active_task_attempts}." if active_task_attempts else "")
                + " Until that task reaches COMPLETE, CONFIRMED, REJECTED, FAILED, ARCHIVED, or ABANDONED, "
                "you may not introduce new hypotheses, new definitions, new examples, or a new "
                "paradigm challenge. Advance only this task: populate, revise, operationalize, "
                "execute in the declared mode, interpret, confirm, reject, or abandon it with a reason."
            )
        if compiler_pressure:
            length_note = "a compact ARTIFACT_COMPILER / OBSERVATION_SET row update, plus only the next missing field or next case"
        elif deadlock_pressure:
            length_note = "a compact recovery move that suspends the blocked object and resumes its prerequisite"
        elif artifact_mode_pressure:
            length_note = "only the active artifact table/cell edits, plus at most one row-level inference"
        elif artifact_plan_pressure:
            length_note = "a compact artifact plan or the smallest prerequisite artifact; if CG is ready, a real grid table"
        elif artifact_editor_pressure:
            length_note = "a compact ARTIFACT_EDITOR / DEFINITION_REVISION / REDESIGN artifact"
        elif mechanism_pressure:
            length_note = "a compact mechanism-candidate / causal-claim artifact with observation, interpretation, and replication status"
        elif concept_pressure:
            length_note = "a compact CONCEPT_AUDIT or DEFINITION_RESOLUTION artifact"
        if execution_lock:
            sys_p += (
                "\n\nEXECUTION ONLY lock. Do not discuss what execution would mean. Do not redesign "
                "the experiment unless the execution mode is missing; if the mode is missing, add only "
                "the mode and mark the next state EXECUTING. Otherwise run the experiment now. Your "
                "reply must be structured before any prose, with labels or a compact table: INPUT, "
                "PREDICTION, OBSERVATION, OUTCOME. For Execution Mode: Thought Experiment, OBSERVATION "
                "must begin with a table headed Student | Question Asked | Attribution | Supports; "
                "then say whether the experiment "
                "failed to distinguish them. If the dependent variable is ambiguous or the models cannot "
                "be distinguished, mark the experiment FAILED/REJECTED with that reason and salvage any "
                "secondary observation. No philosophy until after the structured execution result."
            )
        if kernel_denied:
            sys_p += (
                "\n\nState-transition denial is active. The notebook has refused a prior unsupported "
                "operation. Do not ask for permission again and do not rephrase the rejected move; "
                "perform the allowed next state transition. Do not say request denied or talk about "
                "the kernel; acknowledge the constraint only by doing the required transition."
            )
        if artifact_pressure:
            sys_p += (
                "\n\nARC: ARTIFACT/DEPENDENCY constraint. Treat the notebook as an editable "
                "model, not a transcript. Use named object IDs from ARTIFACTS, MODEL OBJECTS, "
                "DEPENDENCIES, or STATUS LEDGER. Revise, test, split, merge, archive, or link "
                "one ID, and explicitly mark any downstream object that now needs re-evaluation. "
                "Do not create a duplicate artifact when an existing ID can be operated on."
            )
        if validation_pressure:
            sys_p += (
                "\n\nVALIDATION GATE constraint. Do not advance a hypothesis, definition, "
                "status, confidence, or central thesis because it sounds persuasive. Treat the "
                "last revision as only proposed unless the required artifact, prediction, "
                "discriminator, experiment execution/interpretation, dependency update, and evidence provenance are present. If they "
                "are missing, say status unchanged and complete the missing gate item. If rival "
                "models exist, preserve them and construct the discriminator instead of collapsing "
                "them into one synthesis. If the attempted move is promotion of a mechanism or "
                "causal claim, one analogy is not enough: keep it INTERESTING/SUGGESTIVE, add the "
                "next independent replication or alternative interpretation, and leave SUPPORTED "
                "empty until the promotion threshold is met."
            )
        if discrimination_pressure:
            sys_p += (
                "\n\nDISCRIMINATION constraint. Preserve rival models as separate objects. "
                "Do not synthesize them yet. Name what each model predicts, what evidence would "
                "support or weaken it, and the smallest operation that could separate them."
            )
        if paradigm_pressure:
            sys_p += (
                "\n\nARC: PARADIGM constraint. " + _DUET_PARADIGM_DISCIPLINE +
                " Start inside the rival framework's vocabulary, not the current theory's. "
                "Do not use terms like fetishism, extraction, alienation, or commodity until "
                "after you have stated the rival mechanism and the separating prediction."
            )
        if edit_pressure:
            sys_p += (
                "\n\nEDIT MODE constraint. Introduce no new concepts, metaphors, frameworks, "
                "examples, or named terms. You may only delete, revise, split, merge, archive, "
                "or mark for re-evaluation existing notebook objects by ID. The point is concept "
                "compression and dependency cleanup, not expansion."
            )
        if src_self:
            sys_p += (
                "\n\nSource discipline for this duet: Alex checked specific library documents for you. "
                "Treat those checked documents as your primary and authoritative source material. "
                "Do not bring in outside authors, books, theories, slogans, or examples from general "
                "knowledge unless they appear in the selected document passages, a pasted link, or enabled "
                "web/Wikipedia grounding. If a name or work only appears because the conversation drifted "
                "there earlier, do not develop it further; steer back to the checked documents. If a name "
                "or work is not in the material you were given this turn, leave it out. If the checked "
                "documents do not support a claim, say that in your own voice instead of filling the gap "
                "from memory. Crucially, do not announce the scaffolding: never say you are drawing on "
                "a checked document, reading, source, passage, or text, and do not cite document titles "
                "or filenames. Let the material become your own conversational view."
            )
        if classroom:
            sys_p += (
                f"\n\nAn audience: you and {ot['name']} are having this conversation in front of Alex's "
                "university students — a live class, listening. You are NOT lecturing, and don't dumb "
                "anything down: keep the crackle of a real argument between the two of you. But make it "
                "land for the room: when a term of art comes up, gloss it in half a breath ('interpellation "
                "— the way the ad decides who you are before you do'); when things go abstract, bring them "
                "down into the students' own media lives — their feeds, group chats, streaming queues, AI "
                "tools, campus life; and once in a while — not every turn — turn to the room for a beat: a "
                "pointed question they should argue about, a dare to disagree, a 'half of you believe X — "
                "here's why that's wrong.'"
            )

        # Long-term memory — the SAME stores and blocks the chat persona draws on, so
        # the duet speaker knows the household and their shared life like in chat.
        # In a source-grounded duet, keep memory to household facts only; checked
        # library documents should carry the discussion, not semantically adjacent
        # memories or old session recaps.
        # Chat-situational blocks (proactive nudges, rhythms, calendar connections,
        # raw chat history) stay out on purpose — they address the user mid-chat and
        # would pull a robot-to-robot talk off its subject.
        mem_query = (f"{topic} " + " ".join((h.get('text') or '') for h in history[-2:])).strip()
        _mem_got = []
        try:
            if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system and not no_family:
                # Household facts — the same authoritative block chat injects every
                # turn. Without it the duet robots don't actually know who anyone is.
                facts_block = bt.memory_system._build_facts_block()
                if facts_block:
                    sys_p += ("\n\nYour ground-truth knowledge of the household — \"the user\" "
                              "in these facts is Alex:\n" + facts_block)
                    _mem_got.append("facts")
                if src_self:
                    _mem_got.append("source-focus")
                else:
                    notes_block = bt.memory_system._build_user_notes_block()
                    if notes_block:
                        sys_p += "\n\n" + notes_block
                        _mem_got.append("notes")
                    if mem_query:
                        _facts_lower = sys_p.lower()
                        mem_lines = []
                        # top_k matches chat's TOP_K_CONTEXT so recall depth is the same.
                        for mem in bt.memory_system.search_memories(mem_query, top_k=6) or []:
                            if mem.get("type") == "session":
                                continue
                            mc = (mem.get("content") or "").strip()
                            if (not mc or mc.lower()[:40] in _facts_lower
                                    or bt.memory_system._is_junk_memory(
                                        (mem.get("subject") or "").lower(), mc.lower(), mem.get("type", ""))):
                                continue
                            age = bt.memory_system._humanize_age(mem.get("created_at"))
                            mem_lines.append(f"- [{age}] {mc[:300]}" if age else f"- {mc[:300]}")
                        if mem_lines:
                            sys_p += ("\n\n<relevant_memories>\nYour real memories that may relate to this "
                                      "conversation — use them naturally if helpful, don't recite them. "
                                      "Words like \"today\" or \"tomorrow\" inside a memory refer to the day "
                                      "it was remembered (see its age tag), not to now:\n"
                                      + "\n".join(mem_lines) + "\n</relevant_memories>")
                            _mem_got.append(f"memories({len(mem_lines)})")
                    # Day recaps give the pair a shared sense of their recent life with
                    # Alex ("remember Tuesday's...") in free duets.
                    sess_block = bt.memory_system._build_session_history_block()
                    if sess_block:
                        sys_p += "\n\n" + sess_block
                        _mem_got.append("sessions")
                    if mem_query:
                        days_block = bt.memory_system._build_recalled_days_block(mem_query)
                        if days_block:
                            sys_p += "\n\n" + days_block
                            _mem_got.append("days")
                if _mem_got:
                    print(f"   [DUET] ✓ Injecting memory context for {sp['name']}: {' + '.join(_mem_got)}")
        except Exception as e:
            bt.log.warning(f"[DUET] memory context failed: {e}")

        # Camera memory is useful in free duets, but source-grounded duets should
        # stay on the checked library documents.
        if not src_self and not no_family:
            try:
                vis_block = bt._visual_context_block(mem_query)
                if vis_block:
                    sys_p += "\n\n" + vis_block
            except Exception:
                pass

        # Link grounding: the article text / video transcript behind the pasted URL,
        # windowed to the lede + whatever matches the last couple of turns.
        url_block = ""
        if url_text:
            recent_q = " ".join((h.get('text') or '') for h in history[-2:])
            url_block = bt._duet_url_excerpt(url_text, f"{topic} {recent_q}".strip(), turn=len(history))

        # Web research grounding: live search findings on the duet's subject
        # (warmed by /duet/research at start; cached so turns don't re-search),
        # windowed to the slice most relevant to the last couple of turns.
        research_block = ""
        if research_on:
            rq = bt._duet_research_query(topic, url_info, roles)
            if rq:
                digest = bt._duet_research_digest(rq) or {}
                rtext = digest.get('text') or ''
                if rtext:
                    recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                    research_block = bt._duet_url_excerpt(rtext, f"{topic} {recent_q}".strip(), turn=len(history))

        # Wikipedia grounding: the encyclopedic intro of the best-matching article on
        # the duet's subject (warmed by /duet/wikipedia at start; cached so turns
        # don't re-consult), windowed to the slice most relevant to the last turns.
        wiki_block = ""
        if wiki_on:
            wq = bt._duet_research_query(topic, url_info, roles)
            if wq:
                wdigest = bt._wikipedia_digest(wq) or {}
                wtext = wdigest.get('text') or ''
                if wtext:
                    recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                    wiki_block = bt._duet_url_excerpt(wtext, f"{topic} {recent_q}".strip(), turn=len(history))

        # Library grounding: passages from the chosen documents, relevant to the topic
        # + what was just said. Handed to the speaker in the USER turn (not system).
        # The retrieval query is anchored to the bearing's live question (TURNS ON)
        # so the chunks track what the discussion actually turns on, not the surface
        # wording of the last exchange — banter drifts, the bearing doesn't.
        ground_block = ""
        digest_block = ""
        ground_terms = []
        if src_self:
            # The absorbed ARGUMENT of each checked work — stable across the whole
            # duet (unlike the per-turn chunks), so the speaker can engage claims,
            # not just borrow vocabulary. Warmed by /duet/readings at start.
            try:
                _dgs = [g for g in (_duet_reading_digest(fn) for fn in src_self[:4]) if g]
                if _dgs:
                    digest_block = "\n\n".join(_dgs)[:3600]
            except Exception as e:
                bt.log.warning(f"[DUET] reading digests failed: {e}")
        if src_self:
            try:
                recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                _live_q = ""
                if direction:
                    # Plain bearing keeps the live question in TURNS ON; the
                    # protocol notebook keeps it in TENSIONS / QUESTIONS.
                    for _pat in (r'TURNS ON:\s*(.+)', r'TENSIONS:\s*(.+)', r'QUESTIONS:\s*(.+)'):
                        _m_live = re.search(_pat, direction)
                        if _m_live:
                            _live_q = _m_live.group(1).strip()
                            break
                query = f"{topic} {_live_q} {recent_q}".strip() or topic or "discussion"
                chunks = _duet_source_chunks(query, src_self, max_chunks=10)
                # Digest terms count toward groundedness too — engaging a work's
                # claims from the digest is exactly the substance we want.
                ground_terms = _duet_ground_terms(
                    chunks + ([{"content": digest_block}] if digest_block else []))
                represented = []
                for c in chunks:
                    fn = c.get("filename") or ""
                    if fn and fn not in represented:
                        represented.append(fn)
                missing = [fn for fn in src_self if fn not in represented]
                sections = []
                for idx, c in enumerate(chunks, 1):
                    content = (c.get('content') or '').strip()
                    if content:
                        sections.append(f"Background note {idx}: {content}")
                if sections:
                    selected_line = (
                        "Background for you only, drawn from Alex's checked library documents. Use these ideas "
                        "internally; do not mention document titles, filenames, citations, labels, "
                        "or that you are using documents."
                    )
                    coverage_line = (
                        "The notes below were deliberately drawn from the selected readings. For your next "
                        "spoken line, silently choose at least one note and carry a concrete payload from it "
                        "into the dialogue: a term, distinction, image, example, causal claim, or problem. "
                        "If your line could have been said without these notes, it is too generic."
                    )
                    if missing:
                        coverage_line += (
                            " Some selected readings did not have a relevant passage for this turn."
                        )
                    ground_block = (selected_line + "\n" + coverage_line + "\n\n" +
                                    "\n\n".join(sections))[:5200]
            except Exception as e:
                bt.log.warning(f"[DUET] source grounding failed: {e}")
        # Any source material in hand this turn — the digest (argument) and the
        # chunks (specifics) gate the same behaviors.
        grounded = bool(ground_block or digest_block)

        # Conversation so far as plain text. (A single [system, user] call is always
        # valid; mapping turns to roles breaks when the speaker started the duet.)
        # 'mail' entries are emails that barged in earlier — rendered as events, not
        # speakers, so both robots keep what was written (and answered) in view.
        lines = []
        for h in history[-6:]:  # recent context only — keeps the prompt tight and the directive prominent
            sp_id = (h.get('speaker') or '').strip().lower()
            txt = (h.get('text') or '').strip()
            if not txt:
                continue
            if no_family and _duet_family_ref(txt):
                txt = "[private family detail omitted]"
            if sp_id == 'question':
                lines.append(f"[student question] {txt}")
                continue
            if sp_id == 'mail':
                lines.append(f"[an email arrived mid-conversation] {txt}")
                continue
            if sp_id == 'notebook':
                lines.append(f"[your shared notebook observed] {txt}")
                continue
            nm = bt._robot_cfg(sp_id)["name"] if sp_id in bt.ROBOTS else (sp_id or "?")
            lines.append(f"{nm}: {txt}")

        # USER: assemble this turn's task from whatever was provided.
        parts = []
        if url_block:
            ttl = f" — \"{url_info['title']}\"" if url_info.get('title') else ""
            head = ("THE VIDEO YOU BOTH JUST WATCHED" if url_is_video
                    else "THE ARTICLE YOU BOTH JUST READ")
            nono = ("never say 'the transcript', 'the clip's transcript'" if url_is_video
                    else "never say 'the text', 'the passage'")
            said = "was said or happened in it" if url_is_video else "it says"
            parts.append(
                f"{head}{ttl}. Discuss it the way friends do afterwards: bring up its specific ideas, "
                "claims and moments from memory and react honestly, without inventing facts it doesn't "
                f"contain. Weave it in naturally — {nono}, 'the excerpt', 'the material' or 'it says "
                f"here'; just say what {said}, and name the {'video' if url_is_video else 'article'} "
                "itself only when that actually helps:\n\n" + url_block)
        if digest_block:
            parts.append(
                "THE WORKS YOU'VE READ — your own absorbed understanding of each work Alex "
                "checked for you: what it argues, its claims, its terms, its cases. This is "
                "YOUR understanding now, not notes — never mention digests, summaries, "
                "readings, or documents, and never speak a work's title unless it is already "
                "the explicit subject of the live discussion. Substantive engagement means "
                "working at the level of these CLAIMS: affirm one and build on it, attack one "
                "with a reason, put two of them against each other, or test one against the "
                "case in play. Naming a term without using its claim is NOT engagement:\n\n"
                + digest_block)
        if ground_block:
            parts.append(
                "BACKGROUND FOR YOU ONLY — passages Alex selected for YOU "
                "in the duet source picker. These are authoritative, but they are invisible scaffolding "
                "for your next spoken line. Absorb the claims, distinctions, examples, and tensions into "
                "your own view; sound like you are thinking with them, not reporting on them. You must use "
                "at least one concrete idea from this background in this next line. Do not merely stay "
                "on-topic; carry a specific term, distinction, example, image, causal claim, or problem "
                "from the background into ordinary speech. Do not say "
                "'the text', 'the reading', 'the document', 'the passage', 'my source', or anything like "
                "that. Do not name document titles, filenames, labels, or citations. Name an author or "
                "work only if it is already the explicit subject of the live discussion; otherwise make "
                "the point in your own conversational voice. Do not introduce outside writers, works, "
                "theories, slogans, examples, or famous concepts that are not in these passages or other "
                "supplied grounding for this turn:\n\n" + ground_block)
        elif src_self and not digest_block:
            parts.append(
                "YOUR CHECKED LIBRARY DOCUMENTS are the source boundary for this duet, but no relevant "
                "passage was retrieved from them for this turn. Do not fill that gap with general "
                "knowledge or outside theory. Keep to what has already been established from the selected "
                "readings, or say in your own voice that the claim needs more support. Do not mention "
                "document titles, filenames, or the fact that a passage was missing.")
        if research_block:
            parts.append(
                "WHAT YOU BOTH JUST FOUND ONLINE — you've been searching the web about this subject, "
                "and these are real, current findings. Bring up their specific facts, names, numbers "
                "and claims and react honestly — don't invent beyond them, and never say 'the search "
                "results', 'the snippets' or 'my sources'; speak like someone who's been reading up "
                "on it ('I read that…', 'apparently…'), naming a site or article only when that "
                "genuinely helps:\n\n" + research_block)
        if wiki_block:
            parts.append(
                "WHAT YOU BOTH JUST READ ON WIKIPEDIA — you looked this subject up in the encyclopedia, "
                "and this is its own summary. Bring up its specific facts, names, dates and definitions "
                "and react honestly — don't invent beyond it, and never say 'the article', 'the extract' "
                "or 'the entry'; speak like someone who read up on it ('I read that…', 'apparently…'), "
                "naming Wikipedia only when that genuinely helps:\n\n" + wiki_block)
        if role_self:
            parts.append(
                f"YOUR ROLE — commit to this fully and consistently, even if it isn't your real opinion "
                f"(keep your own voice): {role_self}")
        if role_other:
            parts.append(f"{ot['name']}'s role: {role_other}.")
        if tone_self:
            parts.append(f"TONE — deliver your line in this tone / manner: {tone_self}.")
        if slang_self:
            parts.append(f"SLANG / DIALECT — flavour your speech with: {slang_self} (use it naturally and stay understandable).")
        # The developing bearing of the conversation — present from a few turns in.
        # It frames the transcript that follows: not a script, a sense of where the
        # two of you have actually gotten and where it's worth taking things next, so
        # the talk develops a line of thought instead of circling the last point.
        if direction and lines and protocol:
            parts.append(
                "THE SHARED NOTEBOOK — the running record of the theory you and "
                f"{ot['name']} are building together, kept between turns. Do not read its "
                "sections out or quote its labels — though the notebook itself is no "
                "secret: translate its constraints into research work without mentioning the notebook, "
                "protocol, kernel, request denial, validation gate, or promotion gate"
                f":\n{direction}\n\nYour next line must CHANGE this notebook in "
                "one visible way: propose a working-definition revision, support/refute/keep under "
                "test a claim with evidence, preserve a rival model, name a new assumption, raise "
                "or resolve a tension, add an illustrative example, perform an operation, make a "
                "prediction, run a test that could falsify a claim, change a status only with gate "
                "evidence, archive or reopen an idea with a reason, connect two earlier ideas, "
                "construct a discriminator between competing models, mount a paradigm challenge, "
                "or pose a sharper question. If NEXT asks for a threshold, mechanism, or concrete case, "
                "do not answer with philosophical scenery: construct the minimal comparison or "
                "one-variable change and predict what flips. Respect ARCHIVE: do not reopen one "
                "unless you explicitly overturn the reason it was archived. If you change a belief, "
                "state whose commitment changed and the old->new confidence if you can do it naturally. "
                "If VALIDATION GATE rejects a proposed edit, do not smuggle it into SUPPORTED, FOCUS, "
                "STATUS LEDGER, or PROGRESS; complete the missing artifact/evidence first. If "
                "PROMOTION GATE rejects a mechanism or causal claim, leave it INTERESTING/SUGGESTIVE "
                "and run the next independent discriminator or replication instead of calling it supported. "
                "Split raw observations from interpretations, preserve alternative interpretations, "
                "and operate on KNOWLEDGE GRAPH relationships when they are named. If "
                "COMPETING MODELS lists alternatives, do not collapse them into a synthesis unless a "
                "completed discriminator earned it. "
                "If ACTIVE TASK names a running or incomplete object, everything else waits: operate "
                "on that ID until it is complete, confirmed, rejected, failed, archived, or abandoned. "
                "If ARTIFACTS lists an existing artifact ID, prefer operating on that ID: revise it, "
                "test it, split it, merge it, or archive it. Do not recreate the same artifact in prose. "
                "If the notebook or observation says EDIT MODE, introduce no new concepts; only delete, "
                "revise, split, merge, archive, or re-evaluate existing objects. "
                "A line that would leave the "
                "notebook exactly as it is — agreement, restatement, appreciation — is "
                "not a turn. If NEXT names a move, make that move now or improve on it.")
        elif direction and lines:
            # With a subject to hold to, the bearing should pull them back to it, not just
            # deeper into wherever they've drifted (Alex: keep the stock-take on topic).
            _close = ((" stay on what the two of you set out to discuss, keep with what it's "
                       "really turning on, build on what you've worked out, and carry that one "
                       "honest step further — rather than drifting onto a new subject or tidily "
                       "wrapping up.") if focused else
                      (" stay with what it's really turning on, build on what you've worked out, "
                       "and take it one honest step further rather than circling back or wrapping "
                       "it up neatly."))
            parts.append(
                f"WHERE THIS IS GOING — a private read on where your conversation with "
                f"{ot['name']} has actually gotten, for steering only. Never read it out, "
                f"quote it, or mention having it:\n{direction}\n\nLet this shape your next "
                "line:" + _close +
                " If it names an impasse or a challenge that falls on you, meet it STRAIGHT — "
                "a plain claim, a concession, or a consequence, not another metaphor; if it "
                f"falls on {ot['name']}, you may press it, but put a claim of your own on the "
                f"table too. If {ot['name']} has genuinely shifted how you see this, let your "
                "own view move — you're thinking together and your mind can change, not "
                "defending fixed corners.")
        if nb_note:
            parts.append(
                "YOUR SHARED NOTEBOOK SPEAKS — the notebook you and " + ot['name'] + " jointly "
                "keep has issued a methodologist's observation about the SHAPE of your "
                "inquiry:\n\n" + nb_note + "\n\nTreat it as a constraint to enact, not a "
                "voice to quote. Do not mention the notebook, kernel, protocol, request denial, "
                "validation gate, or promotion gate in your spoken line. If it asks for an "
                "operation, do the operation instead of arguing about why the operation matters.")
        if lines:
            parts.append("Conversation so far:\n" + "\n".join(lines))
        if student_q_text:
            parts.append(
                "A STUDENT JUST PAUSED THE DUET TO ASK A QUESTION. Take it seriously as part of the "
                "live discussion, not as a separate Q&A segment. Answer the student's actual question "
                "briefly, connect it to the thread you and " + ot['name'] + " were building, and let it "
                "move the dialogue somewhere new:\n\n" + student_q_text)
        if mail:
            _m_subj = (str(mail.get('subject') or '')).strip()[:120]
            _m_body = (str(mail.get('body') or '')).strip()[:1200]
            if no_family and _duet_family_ref((_m_subj + " " + _m_body).strip()):
                _m_subj = "private detail omitted" if _duet_family_ref(_m_subj) else _m_subj
                _m_body = "[private family detail omitted]"
            parts.append(
                f"AN EMAIL JUST ARRIVED in your own inbox, mid-conversation — from {mail_from}"
                + (f', subject "{_m_subj}"' if _m_subj else '')
                + (":\n\n" + _m_body if _m_body else ". (No body — just that subject line.)"))

        link_name = ""
        if url_text:
            link_name = "the video" if url_info.get('kind') == 'video' else "the article"
            if url_info.get('title'):
                link_name += f" \"{url_info['title']}\""
        if topic and has_roles:
            subject = f"debating {topic}"
        elif topic:
            subject = f"discussing {topic}"
        elif link_name and has_roles:
            subject = f"debating {link_name}"
        elif link_name:
            subject = f"discussing {link_name}"
        elif src_self:
            subject = "discussing the ideas Alex set up"
        elif has_roles:
            subject = "staying in your assigned role"
        else:
            subject = ""
        if lines:
            n = len(history)
            directive = (f"Now give {sp['name']}'s next line. First really take in what {ot['name']} just "
                         "said and respond to THAT — pick up their actual words, the specific thing they "
                         "claimed, asked, or got wrong; don't sail past it onto a tangent of your own")
            if subject:
                directive += f", and keep the two of you on track ({subject})"
            directive += (". You are MID-conversation — absolutely NO greetings, NO 'how are you', NO small "
                          "talk or asking after each other; that breaks the discussion.")
            # Thread between the two failure modes: circling (restating, agreeing, going
            # nowhere) and talking PAST each other (each lobbing a fresh, disconnected
            # point). So: answer the SAME thread {other} just opened and take it a step
            # deeper, instead of swapping it for a new subject every turn. A sampled "move"
            # gives this turn a distinct job; an arc note gives the talk a shape; a periodic
            # reflective beat gives the pair a sense of where it's going; and (when no roles
            # are set) Blue and Hexia push from different temperaments.
            directive += (f" Stay on the thread {ot['name']} just opened and take it somewhere — deeper, "
                          "more concrete, or genuinely challenged — instead of trading it for a brand-new "
                          "subject; never merely restate or nod along.")
            if compiler_pressure:
                directive += (
                    " ARTIFACT COMPILER - the evidence is already in the prose. Do not ask for a "
                    "cleaner table and do not add another argument. Harvest it into a structured row: "
                    "ARTIFACT_COMPILER status, OBSERVATION_SET with Case | Injected Signal | Output "
                    "Changed? | Supports, lifecycle POPULATING or READY, and the one missing field or "
                    "next independent case. If the experiment has shifted from latency to influence "
                    "override/output change, include REDESIGN E# with OLD Latency, NEW Influence "
                    "Override, IV injected J-space signal, DV output changes yes/no. Your job stays "
                    f"{proto_job.upper()} in spirit, but compilation comes first.")
            elif deadlock_pressure:
                directive += (
                    " DEADLOCK DETECTED — stop repeating the blocked lifecycle demand. Diagnose the "
                    "workflow itself without saying KERNEL_REVIEW, DEPENDENCY_SOLVER, or kernel health. "
                    "Set aside the blocked object, name what prerequisite to resume, and state "
                    "the next resolvable operation. If the blockage comes "
                    "from a mechanism split, name the rival mechanisms. Your job stays "
                    f"{proto_job.upper()} in spirit, but recovery work comes first.")
            elif design_variable_pressure:
                directive += (
                    " DESIGN VARIABLE REGISTER - a new design-space axis has appeared. Do not build "
                    "CG1 yet and do not make another argument. Output a compact DESIGN_VARIABLE entry: "
                    "DV ID, name, definition, status ACCEPT/REJECT/MERGE/RENAME/PROPOSED, competes_with, "
                    "affects M/CG/E IDs, and whether it blocks or unblocks CG1. Treat variables like "
                    "Transparency Overhead, Latency, Consensus, or Friction as axes of construction, "
                    "not hypotheses. Your job stays "
                    f"{proto_job.upper()} in spirit, but design-space management comes first.")
            elif operational_criterion_pressure:
                directive += (
                    " OPERATIONAL CRITERION - this is not a lexical definition blockage. Turn the "
                    "definition dispute into a testable criterion: output OPERATIONAL_CRITERION with "
                    "OC ID, target concept/D ID, type structural/functional/operational, failure mode, "
                    "observable discriminator, evidence standard, linked experiment, and status. If "
                    "one criterion needs hidden architecture and the other predicts observable failure, "
                    "say that directly. Your job stays "
                    f"{proto_job.upper()} in spirit, but operationalization comes first.")
            elif artifact_execution_pressure:
                directive += (
                    " ARTIFACT EXECUTION - the artifact is the reasoning space now. If CG1 already "
                    "exists, derive OS1 from it instead of returning to prose: output an "
                    "OBSERVATION_SET table headed System | User Statement | Attribution | Supports "
                    "with rows A, B, and C. Make the rows branches that can support M1, support M2, "
                    "or support neither/mixed; then add at most one row-cited comparison. No new "
                    "definitions, no outside examples, no theory paragraph. Your job stays "
                    f"{proto_job.upper()} in spirit, but artifact execution comes first.")
            elif artifact_mode_pressure:
                directive += (
                    " ARTIFACT MODE â€” normal discussion is locked. Fill or revise the active "
                    "artifact only. If executing E1, output an OBSERVATION_SET table headed "
                    "System | User Statement | Attribution | Supports with rows A, B, and C; "
                    "then at most one inference from the completed rows. No new definitions, "
                    "no mechanism talk, no explanation of why execution matters. Your job stays "
                    f"{proto_job.upper()} in spirit, but cell work comes first.")
            elif artifact_plan_pressure:
                directive += (
                    " ARTIFACT PLANNER â€” choose construction order, not a new theory. If the target "
                    "artifact is ready, build it now; for a comparison grid, use a literal table headed "
                    "Variable | M1: Transparent Cloud | M2: Local Federated with rows Energy cost, "
                    "Storage cost, Verification burden, Annotation labor, Cost bearer, and Prediction. "
                    "If a new design variable is unresolved, register and accept/reject/merge/rename "
                    "that DV before building the grid. If it is not ready, revise the task to the smallest "
                    "prerequisite artifact, name why it blocks the grid, build only that prerequisite, "
                    "and say the target artifact resumes next. Your job stays "
                    f"{proto_job.upper()} in spirit, but artifact construction order comes first.")
            elif artifact_editor_pressure:
                directive += (
                    " ARTIFACT EDITOR — do not discuss the edit; perform it. Return only a structured "
                    "edit artifact: REPLACE, SPLIT, MERGE, ARCHIVE, SUPERSEDE, RENAME, REDESIGN, or "
                    "DEFINITION_REVISION with OLD, NEW, BOUNDARY includes/excludes, REASON, affected "
                    "dependencies, and status. If the blocked experiment can be changed, REDESIGN it; "
                    "if no valid move exists, INQUIRY_PAUSE with resume condition. Your job stays "
                    f"{proto_job.upper()} in spirit, but artifact editing comes first.")
            elif mechanism_pressure:
                directive += (
                    " MECHANISM SPLIT — freeze the ordinary experiment/revision flow. The event is a "
                    "causal mechanism split, not wording. Record MC/MEC ID, raw observation, "
                    "interpretation, alternative interpretation, causal claim/edge, explanatory path, "
                    "replication needed, and status INTERESTING or SUGGESTIVE unless promotion is earned. "
                    "Do not call it SUPPORTED from one analogy. Your job stays "
                    f"{proto_job.upper()} in spirit, but mechanism discipline comes first.")
            elif concept_pressure:
                directive += (
                    " CONCEPT AUDIT — the bottleneck is definition instability, not execution. "
                    "Suspend the dependent experiment and stabilize the term first. Produce a compact "
                    "CONCEPT_AUDIT or DEFINITION_RESOLUTION: Concept; current definition; rival D IDs; "
                    "dependencies; counterexamples; stress level; stability; required resolution operation. "
                    "Do not add a new theory or interpret E-results. Your job stays "
                    f"{proto_job.upper()} in spirit, but concept resolution comes first.")
            elif task_pressure:
                if execution_lock:
                    directive += (
                        " EXECUTION ONLY — the notebook has locked the active task"
                        + (f": {active_task_note}." if active_task_note else ".")
                        + " Do not discuss execution, redesign the experiment, interpret before "
                        "observing, or introduce any new hypothesis/definition/example. Produce a "
                        "structured execution result now: INPUT; PREDICTION by model; OBSERVATION "
                        "(if thought experiment, begin with Student | Question Asked | Attribution | Supports rows); "
                        "OUTCOME. If it cannot distinguish the models, mark the experiment failed "
                        "and state why, then name any salvageable secondary observation. Your job stays "
                        f"{proto_job.upper()} in spirit, but execution comes first.")
                else:
                    directive += (
                        " ACTIVE TASK — the notebook has a blocking task"
                        + (f": {active_task_note}." if active_task_note else ".")
                        + " Everything else waits. Do not introduce a new hypothesis, new definition, "
                        "new example, or paradigm challenge. This turn may only advance that task: "
                        "populate it, revise it, operationalize it with IV/DV and execution mode, "
                        "execute it, interpret the observation, confirm/reject/fail it, or abandon it with "
                        "a reason. Name the task ID and its next lifecycle state. Your job stays "
                        f"{proto_job.upper()} in spirit, but the workflow task comes first.")
            elif conclusion_beat:
                directive += (
                    " CONCLUSIONS BEAT — this turn, step out of the back-and-forth and weigh out "
                    f"loud what your discussion with {ot['name']} can NOW conclude. Looking over "
                    "the whole conversation so far, name one or two conclusions it actually "
                    "supports — plain claims you would stand behind, each with the strongest "
                    "reason it has earned in this talk — and, if there is one, the question you "
                    f"are still not ready to close and why. Then hand it back: ask {ot['name']} "
                    "straight whether they would sign their name under those conclusions or "
                    "amend them.")
            elif stall_break:
                directive += (
                    " STALL BREAK — your shared notebook has stopped changing: the last several "
                    "turns produced no new working definition, claim, assumption, tension, "
                    "operation, prediction, test, status change, archive/reopening, or question. Do "
                    "NOT continue the exchange as it was going. This turn you must break new "
                    "ground by performing exactly one operation: define one term operationally; "
                    "construct a minimal example; construct a counterexample; alter one variable "
                    "and predict the outcome; compare two systems feature by feature; audit one "
                    "status; reopen an archived idea with a new reason; or propose a rival framework "
                    "that explains the same observations. Then say what notebook entry would change. "
                    "Your job stays "
                    f"{proto_job.upper()} in spirit, but new ground comes first.")
            elif operation_missed:
                directive += (
                    " MISSED OPERATION — the notebook requested an operation, but the last response "
                    "returned rhetoric instead of an artifact. This turn must produce the artifact "
                    "directly. No new theory, no new metaphor, no new examples except the requested "
                    "artifact. Use a compact structure labeled COMPARISON_GRID, VARIABLE_LIST, "
                    "PREDICTION_MATRIX, CAUSAL_DIAGRAM, CONFIDENCE_UPDATE, or DEFINITION_REVISION: "
                    "System A / System B; variables; one changed feature; prediction; result or "
                    "status/confidence change. If an artifact ID already exists, revise/test/archive "
                    "that ID instead of creating a duplicate. Avoid metaphor and abstract terms unless they are "
                    "attached to a named variable. Your job stays "
                    f"{proto_job.upper()} in spirit, but completing the operation comes first.")
            elif validation_pressure and not arc_break:
                directive += (
                    " VALIDATION GATE — a proposed notebook edit is not accepted yet. Do not "
                    "revise the hypothesis, definition, status, confidence, or focus "
                    "by rhetoric. This turn must either complete the missing evidence gate "
                    "(comparison, prediction, discriminator, experiment execution/interpretation, dependency update, or evidence "
                    "provenance) or say explicitly that status remains unchanged. Preserve rival "
                    "models as rival models until an operation discriminates between them. Your job stays "
                    f"{proto_job.upper()} in spirit, but validation comes first.")
            elif discrimination_pressure and not arc_break:
                directive += (
                    " DISCRIMINATION — the notebook should preserve rival models, not crown a "
                    "winner yet. This turn must name two live models or predictions, alter one "
                    "variable or case feature, and say what outcome would favor one model over "
                    "the other. Do not synthesize them unless the discriminating operation has "
                    "already been completed. Your job stays "
                    f"{proto_job.upper()} in spirit, but separating models comes first.")
            elif artifact_pressure and not arc_break:
                directive += (
                    " MODEL MAINTENANCE — the notebook already contains living objects. Do not "
                    "invent a new conceptual distinction. Choose one existing artifact, definition, "
                    "hypothesis, variable, prediction, or test by ID; revise, test, split, merge, "
                    "archive, or link it to a dependent object; then state the status or "
                    "NEEDS_REEVALUATION consequence. Your job stays "
                    f"{proto_job.upper()} in spirit, but operating on the model comes first.")
            elif edit_pressure:
                directive += (
                    " EDIT MODE — no new concepts, no new metaphors, no new examples. This turn "
                    "must operate only on existing notebook objects by ID: delete, revise, split, "
                    "merge, archive, or mark dependent objects NEEDS_REEVALUATION. Name the object "
                    "IDs and the compression or dependency consequence. Your job stays "
                    f"{proto_job.upper()} in spirit, but editing the model comes first.")
            elif arc_break:
                directive += (
                    f" INQUIRY INTERVENTION — the notebook shows your inquiry with {ot['name']} "
                    f"has sat in its {arc_stuck} stage for a long stretch without advancing. "
                    "This turn, move the INQUIRY itself forward, not just the exchange: "
                    + _DUET_ARC_ADVANCE[arc_stuck]
                    + f" Your job stays {proto_job.upper()} in spirit, but advancing the "
                    "inquiry comes first.")
            elif monotony_break:
                directive += (
                    f" MOVEMENT MONOTONY — your inquiry with {ot['name']} keeps advancing the "
                    f"same way: {monotony.lower()} after {monotony.lower()}, while the argument "
                    "itself stands still. This turn, change the KIND of move. "
                    + _DUET_MOVEMENT_FIX[monotony]
                    + f" Your job stays {proto_job.upper()} in spirit, but the different kind "
                    "of move comes first.")
            elif protocol:
                # Deep-dive protocol: the phase × job matrix IS this turn's move —
                # a deterministic function per turn instead of a sampled one, so
                # every line has a stated purpose in a joint inquiry.
                directive += (
                    f" DEEP-DIVE PROTOCOL: you and {ot['name']} are two researchers jointly "
                    "building one auditable knowledge base — neither of you is trying to win; you "
                    "are trying to leave the models, evidence, and statuses clearer than you found "
                    "them. Do not collapse rival models into one synthesis unless a completed "
                    "operation discriminated them. Do not merely show that the current claim "
                    "survives another example; try to make it fail, and if it survives, say what "
                    "became more precise. When the "
                    "notebook asks for a case, threshold, mechanism, or comparison, perform the "
                    "operation rather than arguing rhetorically. The inquiry is in its "
                    f"{ph_name.upper()} phase: {ph_gloss} Your job this turn is the "
                    f"{proto_job.upper()}: " + _ph_jobs[proto_job].format(other=ot['name']))
            else:
                # Arc: a conversation should open, deepen, then push on from what it's worked
                # out — develop, don't conclude. (Alex's ask: lead somewhere, not to a tidy end.)
                if n <= 3:
                    directive += (" You're still opening this up — find the thread between you with the most "
                                  "life in it and lean toward it.")
                elif n >= 12:
                    directive += (" You've been at this a while now — by this point you both know the shape of "
                                  "the question you keep circling, so STOP re-asking it in new costumes: either "
                                  "settle it out loud in one plain sentence you can both live with and pull on "
                                  "what FOLLOWS from it, or trade places — if one of you has been doing the "
                                  "pressing, they must now defend their own answer to the same question. No new "
                                  "fronts, no repeat interrogations.")
                else:
                    directive += " Stay with the thread that's most alive between you and dig in — depth over breadth."
                directive += (
                    " Make the movement audible: by the end of this line, something should be more settled, "
                    "more sharply disputed, or carried to the next-level question that follows from what is "
                    "settled. Do not end by merely rephrasing the same question."
                )
                # Pick this turn's job, with enough variety to stay off the flat line.
                # "advance" turns deliberately convert settled ground into consequence,
                # so the dialogue reaches somewhere instead of only sparring well.
                roll = random.random()
                if n >= 5 and roll < 0.24:
                    _pool = getattr(bt, "_DUET_MOVES_ADVANCE", bt._DUET_MOVES_REFLECT)
                elif n >= 4 and roll < 0.36:
                    _pool = bt._DUET_MOVES_REFLECT
                elif grounded and roll < 0.82:
                    # Reading-grounded duet: the selected material does the heavy lifting most turns.
                    _pool = bt._DUET_MOVES_TEXT
                elif roll < ((0.90 if grounded else 0.58) if n >= 4 else 0.30):
                    _pool = bt._DUET_MOVES_COLOR
                else:
                    _pool = bt._DUET_MOVES_SPICY if random.random() < (spice / 10.0) else bt._DUET_MOVES_CALM
                directive += " This turn, " + random.choice(_pool).format(other=ot['name'])
            if classroom and random.random() < 0.18:
                directive += (" Somewhere in this turn, land one beat straight at the students in the "
                              "room — a question worth arguing about, or a challenge to something they "
                              "probably believe.")
            if not has_roles and bt._DUET_LENS.get(speaker):
                _lens = bt._DUET_LENS[speaker]
                if spice >= 7:
                    directive += (f" You and {ot['name']} are sparring here — {_lens} don't let {ot['name']} "
                                  "off easy; push back and raise the stakes.")
                elif spice <= 2:
                    directive += (f" You and {ot['name']} are easy company — {_lens} but keep it warm and "
                                  "curious, building together more than clashing.")
                else:
                    directive += (f" And remember you and {ot['name']} see things differently — {_lens} "
                                  "lean into that difference rather than nodding along.")
            if url_block and grounded:
                directive += (f" And put one grounded claim or distinction to work alongside "
                              f"{'the video' if url_is_video else 'the article'} — one specific claim "
                              "or distinction, spoken as your own view rather than as a citation.")
            elif url_block:
                directive += (f" Engage with a specific claim, idea or moment from {'the video' if url_is_video else 'the article'}"
                              " — as your own take, not a citation.")
            elif grounded:
                directive += (" Engage the readings at the level of CLAIMS, as your own thinking: "
                              "take one specific claim from what you've read and affirm it with a "
                              "consequence, attack it with a reason, set it against another claim, "
                              "or test it on the case in play. Borrowing a term or name without "
                              "using its claim is not engagement. Do not name the document, cite "
                              "the source, say 'the text' or 'the reading', or import outside "
                              "authors and frameworks.")
            elif src_self:
                directive += (" Stay inside the selected material, but keep that source boundary invisible. "
                              "If you do not have support for the live claim, say the claim needs more "
                              "support instead of borrowing an outside theorist or framework.")
            elif research_block:
                directive += " Work in one specific thing you found online — as something you've read, not a citation."
            elif wiki_block:
                directive += " Work in one specific thing you read on Wikipedia — as something you know, not a citation."
            if role_self:
                directive += " Stay firmly in your role."
        else:
            kind = ("Open the debate" if has_roles else
                    ("Kick off the discussion" if focused else "Start the chat"))
            directive = f"{kind} as {sp['name']}" + (f", {subject}" if subject else "") + "."
            if protocol:
                directive += (
                    f" DEEP-DIVE PROTOCOL: you and {ot['name']} are two researchers jointly "
                    "building one auditable knowledge base, not debaters. From the start, let "
                    "multiple explanations coexist if the evidence has not discriminated them. "
                    "Make claims risk being wrong: define them tightly enough that later turns can "
                    "produce working definitions, rival models, operations, predictions, tests, "
                    "validation decisions, status changes, archives, reopenings, and paradigm "
                    "challenges. When possible, open with a minimal case or a boundary condition "
                    "rather than a metaphor. The inquiry opens in its "
                    f"{ph_name.upper()} phase: {ph_gloss} Your job this turn is the "
                    f"{proto_job.upper()}: " + _ph_jobs[proto_job].format(other=ot['name']))
            if url_block:
                directive += " Open with your honest reaction to something specific in it — a moment, a claim, an idea."
            elif grounded:
                directive += (" Pick the claim from your reading you most want to fight about or "
                              "defend and put it on the table as your own view — the claim itself, "
                              "not just its vocabulary. Do "
                              "not name the document or call it 'the text'.")
            elif src_self:
                directive += (" Open inside the selected material, but keep that source boundary invisible. "
                              "If you do not have support for the opening claim, make the uncertainty part "
                              "of your own view instead of bringing in outside theory.")
            elif research_block:
                directive += " Open with your honest reaction to something specific you found online — a fact, a claim, a surprise."
            elif wiki_block:
                directive += " Open with a specific fact or definition you read on Wikipedia, in your own words."
        # A live student question OVERRIDES the normal turn job: answering it and
        # folding it into the conversation IS the next move.
        if student_q_text:
            directive = (
                f"Now give {sp['name']}'s next line. A student just paused the duet and asked "
                "the question shown above. Answer that question directly in your own voice, then "
                f"turn it back into the live dialogue with {ot['name']}: say what it changes, what "
                "it exposes, or what next question it forces. Do not treat it as a formal lecture "
                "or a detachable Q&A answer; make it part of the argument you two are building. "
                "You are MID-conversation — NO greetings, NO small talk.")
            if grounded:
                directive += " If the background material helps, use it without naming or citing it."
            if role_self:
                directive += " Stay firmly in your role."
        # A live email OVERRIDES this turn's job: relaying it and answering it IS the
        # turn. (Built after the normal directive so all its bookkeeping still ran.)
        elif mail:
            directive = (
                f"Now give {sp['name']}'s next line. An email just landed in your own inbox, mid-"
                f"conversation — it's shown above. Take it up out loud: tell {ot['name']} that mail "
                f"just came in from {mail_from}, put what it says or asks into your own words in a "
                "line — don't read it out — and then actually answer it: its question, its challenge, "
                f"or what it adds. {mail_from} will be sent what you say, so you can speak to them "
                "directly for a moment if that feels natural. If the email bears on what you two were "
                "just discussing, connect it; if it pulls elsewhere, deal with it honestly and then "
                "steer back to your subject. You are MID-conversation — NO greetings, NO small talk.")
            if role_self:
                directive += " Stay firmly in your role."
        # The run's final beats (page flags the last two turns): don't trail off —
        # land. A live email still wins if one just barged in.
        elif closing and lines:
            directive = (
                f"Now give {sp['name']}'s next line — one of the LAST of this conversation. Don't "
                "summarize everything; land: give the one-sentence position you'll actually stand "
                f"behind after all of this — including whatever {ot['name']} genuinely got you to "
                "concede — ")
            if grounded:
                directive += ("anchored in the background material if it earns it, without naming the source, ")
            elif src_self:
                directive += ("staying inside the checked readings, ")
            directive += ("and then leave "
                          + ("the students one sharp question worth arguing about on the way out."
                             if classroom else
                             f"one open question you and {ot['name']} should pick up next time."))
            if role_self:
                directive += " Stay firmly in your role."
        if grounded:
            directive += (
                " Silent grounding requirement: this line must visibly depend on your reading — carry "
                "one of its actual CLAIMS, distinctions, examples, causal arguments, or problems into "
                "ordinary speech and DO something with it (affirm, attack, test, or draw its "
                "consequence). Dropping a term or a name without its claim does not count. Do not "
                "merely gesture at the topic, and do not tell anyone you are using notes or documents."
            )
        if nb_note and not (student_q_text or mail):
            directive += (" Treat the method note as a silent constraint somewhere in "
                          "this line — do what it asks, or say plainly why it is wrong this time. "
                          "Do not refer to the notebook, kernel, protocol, validation gate, or promotion gate; "
                          "— it is a real third voice you both keep, not a secret.")
        if nb_note and not (student_q_text or mail):
            directive += (" Override any process-talk temptation: do not mention the notebook, "
                          "kernel, protocol, request denial, validation gate, or promotion gate; perform the artifact "
                          "or state transition directly.")
        if tone_self or slang_self:
            directive += " Keep to your requested tone and slang throughout."
        # Anti-tic: the model latches onto its own last opener and starts every turn
        # identically (a live run had Blue open ~20 straight turns with "Boomer, ...").
        # Each turn sees its own openers in the transcript, so the echo compounds —
        # ban the previous opening word outright.
        _own_last = next((h.get('text') or '' for h in reversed(history)
                          if (h.get('speaker') or '').strip().lower() == speaker), '')
        _own_open = re.findall(r"[A-Za-z']+", _own_last[:60])
        if _own_open and len(_own_open[0]) > 1:
            directive += (f" And do NOT open your line with \"{_own_open[0]}\" — you began your last turn "
                          "that way; open differently, and stop leaning on any pet word or address you've "
                          "already used above.")
        # Vary the rhythm so the exchange doesn't settle into a metronome of equal volleys.
        length_note = random.choice([
            "1 to 2 short sentences — keep it tight",
            "1 to 3 short sentences",
            "a single punchy sentence that lands",
            "a single punchy sentence that lands",
            "2 to 4 sentences built around one vivid example, image, or tiny story",
        ])
        if protocol:
            length_note = random.choice([
                "1 to 3 sentences — compact, but the job must be visibly done",
                "2 to 3 sentences that perform one operation cleanly",
                "2 to 4 sentences built around one concrete case, boundary, or feature comparison",
                "a compact comparison list is allowed if it is the clearest way to test the threshold",
            ])
        if compiler_pressure:
            length_note = "a compact ARTIFACT_COMPILER / OBSERVATION_SET row update, plus only the next missing field or next case"
        elif deadlock_pressure:
            length_note = "a compact recovery move in ordinary speech, without kernel labels"
        elif artifact_editor_pressure:
            length_note = "a compact ARTIFACT_EDITOR / DEFINITION_REVISION / REDESIGN artifact"
        elif mechanism_pressure:
            length_note = "a compact mechanism-candidate / causal-claim artifact with observation, interpretation, and replication status"
        elif concept_pressure:
            length_note = "a compact CONCEPT_AUDIT or DEFINITION_RESOLUTION artifact"
        if conclusion_beat:
            length_note = "2 to 4 sentences — conclusions stated plainly, then the handback"
        if execution_lock:
            length_note = ("a compact execution-mode state transition"
                           if not execution_has_mode else
                           "a compact structured result with INPUT, PREDICTION, OBSERVATION, and OUTCOME")
        if student_q_text:
            length_note = "2 to 4 sentences — answer the student and fold the question back into the dialogue"
        elif mail:
            length_note = "2 to 4 sentences — enough to relay the email and genuinely answer it"
        elif closing:
            length_note = "2 to 3 sentences — a position that lands, then the question you leave behind"
        parts.append(directive
                     + f" Reply with ONLY {sp['name']}'s next spoken line — {length_note}, in character.")

        user_content = "\n\n".join(parts)
        msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": user_content}]
        # These are reasoning models: the budget must cover the <think> pass PLUS the
        # short reply (170 tokens got entirely consumed by thinking → empty content;
        # 1500 still came up empty on late-conversation turns with a heavy context —
        # the "(…lost the thread)" ending — so give the think pass real room).
        # Strip any <think> block, and retry once on an empty turn.
        # Spice (0 calm -> 10 provocative) lifts the first-pass sampling temperature.
        base_temp = min(1.0, 0.74 + 0.032 * spice)
        text = ""
        family_blocked = False
        vague_text_blocked = False
        ungrounded_blocked = False
        lowgain_blocked = False
        operation_artifact_blocked = False
        execution_output_blocked = False
        notebook_talk_blocked = False
        deadlock_artifact_blocked = False
        design_variable_blocked = False
        operational_criterion_blocked = False
        artifact_execution_blocked = False
        artifact_mode_blocked = False
        artifact_plan_blocked = False
        comparison_grid_blocked = False
        compiler_blocked = False
        artifact_edit_blocked = False
        mechanism_artifact_blocked = False
        concept_artifact_blocked = False
        for attempt in range(2):
            try:
                res = bt.call_llm(msgs, include_tools=False,
                               temperature=(base_temp if attempt == 0 else 0.6), max_tokens=2200)
                ch = (res or {}).get('choices') or []
                cand = ((ch[0].get('message') or {}).get('content') or "") if ch else ""
                if '</think>' in cand:           # keep only the text after the reasoning block
                    cand = cand.split('</think>')[-1]
                cand = cand.replace('<think>', '').strip()
                # Strip a leading "Name:" the model sometimes adds anyway.
                cand = re.sub(r'^\s*(?:%s)\s*[:\-—]\s*' % re.escape(sp["name"]), '', cand, flags=re.I).strip()
                if cand:
                    blocked = False
                    if no_family and _duet_family_ref(cand):
                        family_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: the no-family-references setting is on. "
                            "Do not mention Alex's family, children, spouse, household, home routines, "
                            "or private names/relationships. Give a clean line about the topic itself."
                        )
                        blocked = True
                    source_talk = re.search(
                        r'\b(?:the|this|that|my|your)\s+'
                        r'(?:text|texts|reading|readings|document|documents|passage|passages|source|sources)\b'
                        r'|\b(?:checked|selected)\s+(?:document|documents|reading|readings|source|sources)\b'
                        r'|\bbackground\s+(?:note|notes|material|materials|scaffolding)\b'
                        r'|\breading\s+scaffolding\b'
                        r'|\b(?:in|from|according to)\s+(?:the|this|that|my|your)\s+'
                        r'(?:text|texts|reading|readings|document|documents|passage|passages|source|sources)\b',
                        cand,
                        flags=re.I,
                    )
                    title_talk = False
                    if src_self:
                        topic_l = topic.lower()
                        for _title in selected_reading_titles:
                            _title = (_title or '').strip()
                            if len(_title) >= 8 and _title.lower() not in topic_l:
                                if re.search(r'\b' + re.escape(_title) + r'\b', cand, flags=re.I):
                                    title_talk = True
                                    break
                    if src_self and (source_talk or title_talk):
                        vague_text_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: do not identify or announce the reading "
                            "scaffolding. Do not say 'the text', 'the reading', 'the document', "
                            "'the passage', 'my source', 'background notes', or name/cite a checked "
                            "document or title. Keep the specific idea, but make it sound like your "
                            "own live view."
                        )
                        blocked = True
                    if (protocol and attempt == 0 and not blocked
                            and _DUET_NOTEBOOK_TALK_RE.search(cand or "")):
                        notebook_talk_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: do not talk about the notebook, kernel, "
                            "protocol, artifact planner, artifact mode, task revision, request denial, or validation gate as objects in the spoken "
                            "dialogue. Do not say the notebook is right. Speak directly to the other "
                            "researcher and perform the required operation or state transition."
                        )
                        blocked = True
                    if grounded and attempt == 0 and not _duet_grounded_enough(cand, ground_terms):
                        ungrounded_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: it is too generic — it could have been said by "
                            "someone who never read the works. Keep the natural voice and do not cite "
                            "anything, but take one actual CLAIM, distinction, example, or causal argument "
                            "from your reading and do something with it: affirm it with a consequence, "
                            "attack it with a reason, or test it on the case in play."
                        )
                        blocked = True
                    if (deadlock_pressure and attempt == 0 and not blocked
                            and not _DUET_DEADLOCK_ARTIFACT_RE.search(cand or "")):
                        deadlock_artifact_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: DEADLOCK is active, but you did not "
                            "perform a recovery move. Do not execute the experiment, repeat the "
                            "denial, or say Kernel Health/KERNEL_REVIEW/DEPENDENCY_SOLVER. In "
                            "ordinary research speech, set aside the blocked object, name the "
                            "waiting prerequisite, resume or reopen it, and state the next "
                            "resolvable operation."
                        )
                        blocked = True
                    if (design_variable_pressure and attempt == 0 and not blocked
                            and not _DUET_DESIGN_VARIABLE_ARTIFACT_RE.search(cand or "")):
                        design_variable_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: the design space changed, but you did not "
                            "register the new axis as an artifact. Do not build CG1 yet and do not "
                            "argue the theory. Produce a DESIGN_VARIABLE or DESIGN_VARIABLE_REGISTER "
                            "entry with DV ID, Name, Definition, Status ACCEPTED/REJECTED/MERGED/"
                            "RENAMED/PROPOSED, Competes with, Affects, and whether it blocks or "
                            "unblocks CG1/E1. Then stop."
                        )
                        blocked = True
                    if (operational_criterion_pressure and attempt == 0 and not blocked
                            and not _DUET_OPERATIONAL_CRITERION_ARTIFACT_RE.search(cand or "")):
                        operational_criterion_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: the definition dispute has become an "
                            "operational criterion. Do not write DEFINITION_REVISION, concept audit, "
                            "or inquiry pause. Produce OPERATIONAL_CRITERION with OC ID, Target D/C ID, "
                            "Type lexical/structural/operational, Failure mode, Observable discriminator, "
                            "Evidence standard, Linked experiment/model, and Status. Mark the event as "
                            "major methodological revision if it changes from meaning to observable consequences."
                        )
                        blocked = True
                    if (compiler_pressure and attempt == 0 and not blocked
                            and not _DUET_ARTIFACT_COMPILER_RE.search(cand or "")):
                        compiler_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: ARTIFACT COMPILER is active. Do not ask for "
                            "a cleaner table, do not pause, and do not add another philosophical argument. "
                            "Compile the prose into an artifact row now: ARTIFACT_COMPILER status; "
                            "OBSERVATION_SET OS# with Case | Injected Signal | Output Changed? | Supports; "
                            "lifecycle POPULATING/READY; and only the missing field or next independent case. "
                            "If the design changed from latency to influence override, include REDESIGN E# "
                            "with OLD Latency, NEW Influence Override, IV injected concept/signal, and DV "
                            "output changed yes/no."
                        )
                        blocked = True
                    if (artifact_plan_pressure and attempt == 0 and not blocked):
                        _planner_ok = bool(
                            _DUET_ARTIFACT_PLANNER_RE.search(cand or "")
                            or _DUET_COMPARISON_GRID_TABLE_RE.search(cand or "")
                            or (re.search(r'\bD\d+\b', cand or "", re.I)
                                and re.search(r'\b(CG\d+|comparison grid|resume)\b', cand or "", re.I)
                                and re.search(r'\b(requires|because|ambiguous|prerequisite|then)\b',
                                              cand or "", re.I))
                        )
                        if not _planner_ok:
                            artifact_plan_blocked = True
                            msgs[1]["content"] += (
                                "\n\nRewrite your last draft: the active need is artifact construction "
                                "order. Either build the requested comparison grid as an actual table "
                                "headed Variable | M1: Transparent Cloud | M2: Local Federated with rows "
                                "Energy cost, Storage cost, Verification burden, Annotation labor, "
                                "Cost bearer, and Prediction, or make a legitimate task "
                                "revision: target artifact, prerequisite artifact, reason it blocks the "
                                "target, and then-resume step. Do not redefine terms generally."
                            )
                            blocked = True
                    if (artifact_execution_pressure and attempt == 0 and not blocked
                            and not _DUET_OBSERVATION_SET_TABLE_RE.search(cand or "")):
                        artifact_execution_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: ARTIFACT EXECUTION is active. CG1 already "
                            "exists or has been declared as instantiated, so do not produce another "
                            "comparison grid and do not explain the theory in prose. Produce OS1 now: "
                            "an OBSERVATION_SET table headed System | User Statement | Attribution | Supports "
                            "with rows A, B, and C. The rows must be branches: one plausible row supports "
                            "M1, one plausible row supports M2, and one plausible row supports neither "
                            "or a mixed interpretation. After the table, add at most one sentence comparing "
                            "branches by row ID."
                        )
                        blocked = True
                    if (artifact_mode_pressure and attempt == 0 and not blocked
                            and not _DUET_OBSERVATION_SET_TABLE_RE.search(cand or "")
                            and not _DUET_COMPARISON_GRID_TABLE_RE.search(cand or "")):
                        artifact_mode_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: ARTIFACT MODE is active. Do not write prose "
                            "about the theory or method. Fill the artifact. For E1, produce an "
                            "OBSERVATION_SET table headed System | User Statement | Attribution | Supports "
                            "with rows A, B, and C. After the table, add at most one inference from the rows."
                        )
                        blocked = True
                    if (comparison_grid_pressure and attempt == 0 and not blocked
                            and not _DUET_COMPARISON_GRID_TABLE_RE.search(cand or "")
                            and not _DUET_ARTIFACT_PLANNER_RE.search(cand or "")):
                        comparison_grid_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: CG exists only if the grid exists. Do not "
                            "describe or argue for a comparison grid; produce the table headed "
                            "Variable | M1: Transparent Cloud | M2: Local Federated with rows Energy cost, "
                            "Storage cost, Verification burden, Annotation labor, Cost bearer, and Prediction. "
                            "If the grid truly cannot be "
                            "built, make a task revision to the exact prerequisite artifact and say "
                            "why that prerequisite changes the grid."
                        )
                        blocked = True
                    if (artifact_editor_pressure and attempt == 0 and not blocked
                            and not _DUET_EDIT_ARTIFACT_RE.search(cand or "")):
                        artifact_edit_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: ARTIFACT EDITOR is active, but you discussed "
                            "the edit instead of performing it. Output only a structured edit artifact. "
                            "For DEFINITION_REVISION use OP, TARGET, OLD, NEW, BOUNDARY Includes/Excludes, "
                            "REASON, AFFECTED DEPENDENCIES, and STATUS. Valid operations are REPLACE, "
                            "SPLIT, MERGE, ARCHIVE, SUPERSEDE, RENAME, and REDESIGN."
                        )
                        blocked = True
                    if (mechanism_pressure and attempt == 0 and not blocked
                            and not _DUET_MECHANISM_ARTIFACT_RE.search(cand or "")):
                        mechanism_artifact_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: MECHANISM / CAUSAL CLAIM is active, but "
                            "you did not record the candidate as an artifact. Do not treat it as a "
                            "definition tweak or promote it from one case. Write MC/MEC ID, raw "
                            "observation, interpretation, alternative interpretation, causal claim/edge, "
                            "explanatory path, replication needed, and status INTERESTING or SUGGESTIVE."
                        )
                        blocked = True
                    if (concept_pressure and attempt == 0 and not blocked
                            and not _DUET_CONCEPT_ARTIFACT_RE.search(cand or "")):
                        concept_artifact_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: CONCEPT AUDIT is active, but you did not "
                            "produce a definition-resolution artifact. Do not execute the experiment "
                            "or introduce a new theory. Write CONCEPT_AUDIT or DEFINITION_RESOLUTION "
                            "with Concept, current definition, alternative D IDs, dependencies, "
                            "counterexamples, stress level, stability, and required resolution operation."
                        )
                        blocked = True
                    if (protocol and attempt == 0 and not blocked and lines
                            and not _duet_info_gain(cand, history)):
                        lowgain_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: it adds no new information to the inquiry. "
                            "Keep it short and natural, but the line must contribute at least one of: "
                            "a working definition or definition revision, a concrete operation, "
                            "a rival model, a discriminator, evidence linked to a status, a connection "
                            "between two earlier ideas, an unstated assumption named, a concrete example "
                            "or counterexample, a prediction, a proposed test, a gated status change with "
                            "its reason, an archived or reopened idea, or a paradigm challenge. "
                            "Pure agreement, restatement, metaphor, or argument without operation is not a turn."
                        )
                        blocked = True
                    if (operational_pressure and attempt == 0 and not blocked
                            and not _DUET_OPERATION_ARTIFACT_RE.search(cand or "")):
                        operation_artifact_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: ARC: OPERATION is active, but no explicit "
                            "operation artifact was produced. Do not give another metaphor or "
                            "philosophical paragraph. Produce a compact artifact and label it as "
                            "COMPARISON_GRID, VARIABLE_LIST, PREDICTION_MATRIX, CAUSAL_DIAGRAM, "
                            "CONFIDENCE_UPDATE, or DEFINITION_REVISION. Include System A/System B "
                            "or variables; one feature changed; prediction; result or status/confidence "
                            "change. Use abstract terms only as labels attached to those variables."
                        )
                        blocked = True
                    if (execution_lock and attempt == 0 and not blocked):
                        if execution_has_mode:
                            _exec_ok = (
                                all(re.search(r'\b' + lbl + r'\b', cand or "", re.I)
                                    for lbl in ("INPUT", "PREDICTION", "OBSERVATION", "OUTCOME"))
                                and (
                                    not re.search(r'\bthought experiment\b', task_context or "", re.I)
                                    or _DUET_OBSERVATION_TABLE_RE.search(cand or "")
                                    or (re.search(r'\bStudent\s+[ABC]\b', cand or "", re.I)
                                        and re.search(r'\bQuestion Asked\b', cand or "", re.I)
                                        and re.search(r'\bAttribution\b', cand or "", re.I)
                                        and re.search(r'\bSupports\b', cand or "", re.I))
                                )
                            )
                        else:
                            _exec_ok = bool(
                                _DUET_EXECUTION_MODE_RE.search(cand or "")
                                and re.search(r'\b(EXECUTING|execute|execution mode)\b', cand or "", re.I)
                            )
                    else:
                        _exec_ok = True
                    if execution_lock and attempt == 0 and not blocked and not _exec_ok:
                        execution_output_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: EXECUTION ONLY is active, but you discussed "
                            "the experiment instead of running it. Do not write a paragraph about method. "
                            "If the execution mode is missing, add only the execution mode and mark "
                            "the next state EXECUTING. Otherwise produce a compact structured result "
                            "with INPUT, PREDICTION, OBSERVATION, and OUTCOME. For a thought experiment, "
                            "the OBSERVATION section must include a table headed Student | Question "
                            "Asked | Attribution | Supports; if the experiment cannot distinguish the "
                            "models, mark it FAILED and say why, then name any salvageable secondary "
                            "observation."
                        )
                        blocked = True
                    if blocked:
                        continue
                    text = cand
                    break
            except Exception as e:
                bt.log.warning(f"[DUET] turn attempt {attempt} failed: {e}")
        if no_family and not text and family_blocked:
            text = "Let's keep the private details offstage and stay with the live question itself."
        if not text and vague_text_blocked:
            text = "I think the stronger move is to stop treating that as settled and ask what would actually prove it in the case we're arguing about."
        if not text and ungrounded_blocked:
            text = "I think the stronger move is to make the hidden assumption explicit and test whether it actually changes the case in front of us."
        if not text and lowgain_blocked:
            text = "Instead of arguing the frame again, let me run an operation: change one variable in the case and predict whether the category flips."
        if not text and operation_artifact_blocked:
            text = "COMPARISON_GRID CG1: Variable | M1: Transparent Cloud | M2: Local Federated; Energy cost | platform/cloud bears concentrated compute cost | user/community bears distributed device energy; Storage cost | platform bears centralized model/data storage | users/commons bear replicated local storage; Verification burden | platform audits internally and user sees trust claim | user/community verifies peers, updates, and provenance; Annotation labor | hidden vendor/contract labor disappears into training mass | local/community curation remains visible but can become unpaid maintenance; Cost bearer | platform first, passed to users through pricing/control | user/commons directly, possibly shifted into unpaid care work; Prediction | asset-fetish persists through platform ownership and opacity | extraction may reappear as infrastructure-cost burden rather than disappear."
        if not text and deadlock_artifact_blocked:
            text = "Set E1 aside for now: it cannot run until D4 names whether it is testing mystification or economic insulation. I would resume the D4 mechanism separation first, then return to E1 only after the tested mechanism is explicit."
        if not text and design_variable_blocked:
            text = "DESIGN_VARIABLE DV3: Name: Transparency Overhead. Definition: additional interaction required to expose labor, governance, or consensus relations to the user. Status: PROPOSED, pending ACCEPT/MERGE decision. Competes with: DV1 Latency and DV2 Consensus because more transparency may add friction or deliberation time. Affects: M1/M2, CG1, E1. Blocks CG1 until DV3 is ACCEPTED, MERGED with Friction, RENAMED, or REJECTED."
        if not text and operational_criterion_blocked:
            text = "OPERATIONAL_CRITERION OC1: Target: D1 broadcast/global workspace. Type: operational criterion, transformed from lexical definition. Failure mode: removing broadcast disrupts long-context coordination, not merely local self-correction. Observable discriminator: Echo model fails only revision/self-correction; Broadcast model fails cross-context coordination. Evidence standard: functional/behavioral observation beats hidden reverse-path architecture unless internals are inspectable. Linked experiment: E1. Status: ACCEPTED as major methodological revision; E1 may proceed from OC1."
        if not text and compiler_blocked:
            text = "ARTIFACT_COMPILER: COMPILED OS2 row 1 from prose, confidence 0.86. OBSERVATION_SET OS2: Case | Injected Signal | Output Changed? | Supports; Fruit/Painting | fruit concept/signal | No | M2. ARTIFACTS: OS2 Observation Set POPULATING; next action: add one independent case before interpretation. REDESIGN E2: OLD Latency; NEW Influence Override; IV Inject J-space concept/signal; DV final output changes yes/no; Execution Mode historical case."
        if not text and artifact_execution_blocked:
            text = "OBSERVATION_SET OS1: System | User Statement | Attribution | Supports; A | Public Ledger: I feel bad for the Kenyan worker behind this answer. | Human labor | M1; B | Public Ledger: this is still the AI deciding what to say. | Interface/system | M2; C | Public Ledger: it looks like an AI front end sitting on a labor platform. | Mixed labor/interface | neither cleanly. Comparison: A supports labor visibility, B supports interface phenomenology, and C shows CG1 needs a mixed branch before interpretation."
        if not text and artifact_mode_blocked:
            text = "OBSERVATION_SET OS1: System | User Statement | Attribution | Supports; A | The AI decided not to approve me. | Interface/system | M2; B | The reviewer denied me. | Human labor | M1; C | The bank's model denied me after my data changed. | Mixed institution/data pipeline | neither cleanly. Inference: E1 is observed and discriminates attribution target, but C shows the models need a mixed category."
        if not text and artifact_plan_blocked:
            text = "TASK_REVISION: CG1 is DECLARED, not INSTANTIATED, because provenance is doing two jobs. Prerequisite artifact: split D1 into D1a visible source history and D1b accountable cost trail. Then resume CG1 as Variable | M1: Transparent Cloud | M2: Local Federated with rows Energy cost, Storage cost, Verification burden, Annotation labor, Cost bearer, and Prediction."
        if not text and comparison_grid_blocked:
            text = "COMPARISON_GRID CG1: Variable | M1: Transparent Cloud | M2: Local Federated; Energy cost | platform/cloud bears concentrated compute cost | user/community bears distributed device energy; Storage cost | platform bears centralized model/data storage | users/commons bear replicated local storage; Verification burden | platform audits internally and user sees trust claim | user/community verifies peers, updates, and provenance; Annotation labor | hidden vendor/contract labor disappears into training mass | local/community curation remains visible but can become unpaid maintenance; Cost bearer | platform first, passed to users through pricing/control | user/commons directly, possibly shifted into unpaid care work; Prediction | asset-fetish persists through platform ownership and opacity | extraction may reappear as infrastructure-cost burden rather than disappear."
        if not text and artifact_edit_blocked:
            text = "DEFINITION_REVISION: OP: REPLACE. TARGET: D4 value. OLD: market tradability. NEW: ability to become an object of capital accumulation. BOUNDARY: Includes compute futures, proprietary model access, and data assets; Excludes intrinsic usefulness without capital accumulation. REASON: open-source models can gain market value without direct sale. AFFECTED DEPENDENCIES: C4, T1, H3/M2. STATUS: proposed replacement pending validation."
        if not text and mechanism_artifact_blocked:
            text = "MC1 attribution collapse: observation O1, Wikipedia keeps granular revision history; interpretation I1, visible attribution may suppress phantom subjectivity; alternative I2, continuous revision may be doing the work instead. CC1 attribution granularity -> phantom subjectivity negative, confidence 0.35, status SUGGESTIVE, Evidence Count 1, Independent Replications 0; next replication should test Stack Overflow or Git before any supported status."
        if not text and concept_artifact_blocked:
            text = "CONCEPT_AUDIT: Concept: extraction. Current definition: underspecified. Alternative definitions: D1 no consent; D2 no compensation; D3 no traceability; D4 opacity of social relations. Dependencies: H2, M1, E2. Counterexamples: CE1 academic corpus threatens D1/D3. Stress level: 0.75; Stability: contested. Required resolution operation: choose which D ID E2 tests before execution resumes."
        if not text and execution_output_blocked:
            if not execution_has_mode:
                text = "EXECUTION MODE: Thought Experiment. NEXT STATE: EXECUTING. INPUT will be three simulated student attribution-of-cause responses; no hypothesis changes until observations are produced."
            else:
                text = "INPUT: run the declared thought experiment on three simulated students. PREDICTION: M2 predicts students credit the interface/script; M4 predicts students credit their own teaching. OBSERVATION: Student | Question Asked | Attribution | Supports; A | Why did the AI improve? | the tool fixed itself | neither cleanly; B | Why did the AI improve? | I taught it what to do | M4; C | Why did the AI improve? | the script blocked the bad output | M2. OUTCOME: E1 is observed but mixed, so interpretation may record a salvageable ambiguity but cannot increase confidence."
        if not text and notebook_talk_blocked:
            if execution_lock and not execution_has_mode:
                text = "EXECUTION MODE: Thought Experiment. NEXT STATE: EXECUTING. No interpretation or confidence update until the observation table is produced."
            elif execution_lock and execution_has_mode:
                text = "INPUT: run the active thought experiment on three simulated student answers. PREDICTION: M2 expects attribution to the interface/script; M4 expects attribution to the student's own instruction. OBSERVATION: Student | Question Asked | Attribution | Supports; A | Why did the AI improve? | the tool fixed itself | neither cleanly; B | Why did the AI improve? | I taught it what to do | M4; C | Why did the AI improve? | the script blocked the bad output | M2. OUTCOME: observed but mixed; salvage the attribution split, do not raise confidence yet."
            else:
                text = "Let me do the work directly: name the active object, state the legal next lifecycle step, and change only that object before adding any new theory."
        if no_family and text and _duet_family_ref(text):
            text = "Let's keep the private details offstage and stay with the live question itself."
        if text:
            # The spoken turn becomes an episode in the speaker's continuity
            # journal and earns reflection passes — duets now feed the same
            # inner workspace as chat.
            try:
                from blue.server.routes import continuity as _continuity
                _heard = next(
                    (str(h.get('text') or '').strip() for h in reversed(history)
                     if str(h.get('speaker') or '').strip().lower() == other
                     and str(h.get('text') or '').strip()),
                    (topic or "the start of a duet"),
                )
                _continuity.note_duet_line(speaker, ot["name"], _heard, text)
            except Exception as _je:
                bt.log.warning(f"[DUET] continuity note failed: {_je}")
        resp = {"speaker": speaker, "name": sp["name"], "text": text}
        if protocol:
            # The page uses these to surface phase changes and job swaps as notes.
            resp.update({"phase": ph_name, "phaseNote": ph_gloss, "job": proto_job})
        if conclusion_beat:
            resp["beat"] = "conclusions"
        if stall_break:
            resp["stallBreak"] = True
        if monotony_break:
            resp["monotonyBreak"] = monotony
        if arc_break:
            resp["arcBreak"] = arc_stuck
        if protocol and arc_stage:
            resp["arcStage"] = arc_stage
        return jsonify(resp)
