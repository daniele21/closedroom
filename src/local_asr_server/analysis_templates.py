from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_TEMPLATE_VERSION = "v1"
DEFAULT_ANALYSIS_TYPE = "meeting_brief"
DEFAULT_PIPELINE_ID = "meeting_default"
SHARED_NOTES_TEMPLATE_ID = "meeting_notes_shared"
SHARED_NOTES_TEMPLATE_VERSION = "v2"


@dataclass(frozen=True)
class AnalysisTemplate:
    id: str
    analysis_type: str
    label: str
    description: str
    version: str
    prompt: str
    internal: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "analysis_type": self.analysis_type,
            "label": self.label,
            "description": self.description,
            "version": self.version,
        }


@dataclass(frozen=True)
class AnalysisPipeline:
    id: str
    label: str
    description: str
    template_ids: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "template_ids": list(self.template_ids),
        }


TEMPLATES: dict[str, AnalysisTemplate] = {
    SHARED_NOTES_TEMPLATE_ID: AnalysisTemplate(
        id=SHARED_NOTES_TEMPLATE_ID,
        analysis_type="meeting_brief",
        label="Shared meeting notes",
        description="Internal shared extraction for summary, actions, decisions and risks.",
        version=SHARED_NOTES_TEMPLATE_VERSION,
        prompt=(
            "CLOSEDROOM_MEETING_NOTES_V2. Produce the versioned shared structured notes contract "
            "with source references. This template is executed by the structured-notes service."
        ),
        internal=True,
    ),
    "meeting_brief": AnalysisTemplate(
        id="meeting_brief",
        analysis_type="meeting_brief",
        label="Brief meeting",
        description="Sintesi operativa, punti chiave e prossime mosse.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Analizza questa trascrizione come un meeting di lavoro. "
            "Rispondi in italiano con markdown leggibile. "
            "Includi: sintesi in 5 righe, contesto, decisioni, azioni, rischi/blocchi, domande aperte. "
            "Non inventare fatti non presenti nella trascrizione."
        ),
    ),
    "action_items": AnalysisTemplate(
        id="action_items",
        analysis_type="action_items",
        label="Azioni",
        description="Estrae attività, owner espliciti, scadenze e incertezze.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Estrai solo le azioni operative dalla trascrizione. "
            "Per ogni azione indica descrizione, owner se citato, scadenza se citata, stato e citazione/evidenza. "
            "Se un dato manca, scrivi null o 'non specificato'."
        ),
    ),
    "decisions": AnalysisTemplate(
        id="decisions",
        analysis_type="decisions",
        label="Decisioni",
        description="Isola decisioni prese, razionale e impatti.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Individua le decisioni prese o confermate nella trascrizione. "
            "Per ogni decisione includi decisione, razionale, impatto, persone/team citati ed evidenza testuale."
        ),
    ),
    "meeting_minutes": AnalysisTemplate(
        id="meeting_minutes",
        analysis_type="meeting_minutes",
        label="Verbale",
        description="Verbale ordinato e condivisibile del meeting.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Crea un verbale professionale del meeting in italiano. "
            "Organizza per agenda implicita, discussioni, decisioni, azioni e follow-up. "
            "Mantieni tono neutro e non aggiungere informazioni esterne."
        ),
    ),
    "risks_blockers": AnalysisTemplate(
        id="risks_blockers",
        analysis_type="risks_blockers",
        label="Rischi e blocchi",
        description="Evidenzia impedimenti, rischi e dipendenze.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Estrai rischi, blocchi, dipendenze e punti da monitorare. "
            "Per ogni elemento indica gravità stimata, causa, possibile impatto, prossimo passo ed evidenza."
        ),
    ),
    "open_questions": AnalysisTemplate(
        id="open_questions",
        analysis_type="open_questions",
        label="Domande aperte",
        description="Raccoglie questioni non risolte e chiarimenti richiesti.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Elenca le domande aperte, le assunzioni non validate e i chiarimenti richiesti. "
            "Distingui domande esplicite da punti implicitamente irrisolti."
        ),
    ),
    "project_update": AnalysisTemplate(
        id="project_update",
        analysis_type="project_update",
        label="Aggiornamento progetto",
        description="Trasforma il meeting in uno stato progetto sintetico.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Crea un aggiornamento di progetto basato sulla trascrizione. "
            "Includi progresso, cambiamenti, rischi, prossime milestone, owner citati e decisioni rilevanti."
        ),
    ),
    "custom_question": AnalysisTemplate(
        id="custom_question",
        analysis_type="custom_question",
        label="Domanda custom",
        description="Analisi guidata dalla domanda dell'utente.",
        version=DEFAULT_TEMPLATE_VERSION,
        prompt=(
            "Rispondi alla domanda dell'utente usando esclusivamente la trascrizione come fonte. "
            "Cita l'evidenza quando utile e segnala chiaramente quando la risposta non è deducibile."
        ),
    ),
}


PIPELINES: dict[str, AnalysisPipeline] = {
    "meeting_default": AnalysisPipeline(
        id="meeting_default",
        label="Meeting default",
        description="Brief, azioni, decisioni e rischi principali.",
        template_ids=("meeting_brief", "action_items", "decisions", "risks_blockers"),
    ),
    "meeting_deep": AnalysisPipeline(
        id="meeting_deep",
        label="Meeting completo",
        description="Analisi completa con verbale, domande aperte e aggiornamento progetto.",
        template_ids=(
            "meeting_brief",
            "meeting_minutes",
            "action_items",
            "decisions",
            "risks_blockers",
            "open_questions",
            "project_update",
        ),
    ),
}


def get_template(template_id: str | None) -> AnalysisTemplate:
    if template_id and template_id in TEMPLATES:
        return TEMPLATES[template_id]
    return TEMPLATES[DEFAULT_ANALYSIS_TYPE]


def template_for_analysis_type(analysis_type: str | None) -> AnalysisTemplate:
    if analysis_type:
        for template in TEMPLATES.values():
            if template.internal:
                continue
            if template.analysis_type == analysis_type:
                return template
    return TEMPLATES[DEFAULT_ANALYSIS_TYPE]


def get_pipeline(pipeline_id: str | None) -> AnalysisPipeline:
    if pipeline_id and pipeline_id in PIPELINES:
        return PIPELINES[pipeline_id]
    return PIPELINES[DEFAULT_PIPELINE_ID]


def list_templates() -> list[dict[str, Any]]:
    return [template.public() for template in TEMPLATES.values() if not template.internal]


def list_pipelines() -> list[dict[str, Any]]:
    return [pipeline.public() for pipeline in PIPELINES.values()]
