# -*- coding: utf-8 -*-
"""OpenCTI CrowdStrike connector utilities module."""

import base64
import calendar
import functools
import logging
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Mapping,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from crowdstrike_client.api.models import Response
from crowdstrike_client.api.models.download import Download
from crowdstrike_client.api.models.report import Actor, Entity, Report

from lxml.html import fromstring

from pycti.utils.constants import CustomProperties

from stix2 import (
    ExternalReference,
    Identity,
    IntrusionSet,
    KillChainPhase,
    Malware,
    MarkingDefinition,
    Relationship,
    Report as STIXReport,
    Vulnerability,
)
from stix2.core import STIXDomainObject, STIXRelationshipObject


logger = logging.getLogger(__name__)


T = TypeVar("T")


def paginate(
    func: Callable[..., Response[T]]
) -> Callable[..., Generator[List[T], None, None]]:
    """Paginate API calls."""

    @functools.wraps(func)
    def wrapper_paginate(
        *args: Any, limit: int = 25, **kwargs: Any
    ) -> Generator[List[T], None, None]:
        logger.info(
            "func: %s, limit: %s, args: %s, kwargs: %s",
            func.__name__,
            limit,
            args,
            kwargs,
        )

        total_count = 0

        _limit = limit
        _offset = 0
        _total = None

        while next_batch(_limit, _offset, _total):
            response = func(*args, limit=_limit, offset=_offset, **kwargs)

            errors = response.errors
            if errors:
                logger.error("Query completed with errors")
                for error in errors:
                    logger.error("Error: %s (code: %s)", error.message, error.code)

            meta = response.meta
            if meta.pagination is not None:
                pagination = meta.pagination

                _meta_limit = pagination.limit
                _meta_offset = pagination.offset
                _meta_total = pagination.total

                logger.info(
                    "Query pagination info limit: %s, offset: %s, total: %s",
                    _meta_limit,
                    _meta_offset,
                    _meta_total,
                )

                _offset = _offset + _limit
                _total = _meta_total

            resources = response.resources
            resources_count = len(resources)

            logger.info("Query fetched %s resources", resources_count)

            total_count += resources_count

            yield resources

        logger.info("Fetched %s resources in total", total_count)

    return wrapper_paginate


def next_batch(limit: int, offset: int, total: Optional[int]) -> bool:
    """Is there a next batch of resources?"""
    if total is None:
        return True
    return (total - offset) > 0


def datetime_to_timestamp(datetime_value: datetime) -> int:
    # Use calendar.timegm because the time.mktime assumes that the input is in your
    # local timezone.
    return calendar.timegm(datetime_value.timetuple())


def timestamp_to_datetime(timestamp: int) -> datetime:
    return datetime.utcfromtimestamp(timestamp)


def datetime_utc_now() -> datetime:
    return datetime.utcnow()


def datetime_utc_epoch_start() -> datetime:
    return datetime.utcfromtimestamp(0)


def create_external_reference(
    source_name: str, external_id: str, url: str
) -> ExternalReference:
    """Create an external reference."""
    return ExternalReference(source_name=source_name, external_id=external_id, url=url)


def create_vulnerability(
    name: str,
    author: Identity,
    external_references: List[ExternalReference],
    object_marking_refs: List[MarkingDefinition],
) -> Vulnerability:
    """Create a vulnerability."""
    return Vulnerability(
        created_by_ref=author,
        name=name,
        labels=["vulnerability"],
        external_references=external_references,
        object_marking_refs=object_marking_refs,
    )


def create_malware(
    name: str,
    aliases: List[str],
    author: Identity,
    kill_chain_phases: List[KillChainPhase],
    external_references: List[ExternalReference],
    object_marking_refs: List[MarkingDefinition],
    malware_id: Optional[str] = None,
) -> Malware:
    """Create a malware."""
    return Malware(
        id=malware_id,
        created_by_ref=author,
        name=name,
        kill_chain_phases=kill_chain_phases,
        labels=["malware"],
        external_references=external_references,
        object_marking_refs=object_marking_refs,
        custom_properties={CustomProperties.ALIASES: aliases},
    )


def create_kill_chain_phase(kill_chain_name: str, phase_name: str) -> KillChainPhase:
    """Create a kill chain phase."""
    return KillChainPhase(kill_chain_name=kill_chain_name, phase_name=phase_name)


def create_intrusion_set(
    name: str,
    aliases: List[str],
    author: Identity,
    primary_motivation: Optional[str],
    secondary_motivations: List[str],
    external_references: List[ExternalReference],
    object_marking_refs: List[MarkingDefinition],
) -> IntrusionSet:
    """Create an intrusion set."""
    return IntrusionSet(
        created_by_ref=author,
        name=name,
        aliases=aliases,
        primary_motivation=primary_motivation,
        secondary_motivations=secondary_motivations,
        labels=["intrusion-set"],
        external_references=external_references,
        object_marking_refs=object_marking_refs,
    )


def create_intrusion_set_from_actor(
    actor: Actor,
    author: Identity,
    primary_motivation: Optional[str],
    secondary_motivation: Optional[str],
    external_references: List[ExternalReference],
    object_marking_refs: List[MarkingDefinition],
) -> IntrusionSet:
    """Create an intrusion set from actor model."""
    name = actor.name
    if name is None:
        name = f"NO_NAME_{actor.id}"

    # Add name without space as alias because the indicator query returns
    # actor names without spaces.
    alias = name.replace(" ", "")
    aliases = [alias]

    secondary_motivations = []
    if secondary_motivation is not None and secondary_motivation:
        secondary_motivations.append(secondary_motivation)

    return create_intrusion_set(
        name,
        aliases,
        author,
        primary_motivation,
        secondary_motivations,
        external_references,
        object_marking_refs,
    )


def create_organization(name: str, author: Optional[Identity] = None) -> Identity:
    """Create an organization."""
    return Identity(
        created_by_ref=author,
        name=name,
        identity_class="organization",
        custom_properties={CustomProperties.IDENTITY_TYPE: "organization"},
    )


def create_sector(name: str, author: Identity) -> Identity:
    """Create a sector."""
    return Identity(
        created_by_ref=author,
        name=name,
        identity_class="class",
        custom_properties={CustomProperties.IDENTITY_TYPE: "sector"},
    )


def create_sector_from_entity(entity: Entity, author: Identity) -> Optional[Identity]:
    """Create a sector from entity."""
    sector_name = entity.value
    if sector_name is None or not sector_name:
        return None
    return create_sector(sector_name, author)


def create_sectors_from_entities(
    entities: List[Entity], author: Identity
) -> List[Identity]:
    """Create sectors from entities."""
    sectors = []
    for entity in entities:
        sector = create_sector_from_entity(entity, author)
        if sector is None:
            continue
        sectors.append(sector)
    return sectors


def create_region(entity: Entity, author: Identity) -> Identity:
    """Create a region"""
    custom_properties: Dict[str, Any] = {CustomProperties.IDENTITY_TYPE: "region"}

    return Identity(
        created_by_ref=author,
        name=entity.value,
        identity_class="group",
        custom_properties=custom_properties,
    )


def create_country(entity: Entity, author: Identity) -> Identity:
    """Create a country"""
    custom_properties: Dict[str, Any] = {CustomProperties.IDENTITY_TYPE: "country"}

    if entity.slug is not None:
        custom_properties[CustomProperties.ALIASES] = [entity.slug.upper()]

    return Identity(
        created_by_ref=author,
        name=entity.value,
        identity_class="group",
        custom_properties=custom_properties,
    )


def create_countries(entities: List[Entity], author: Identity) -> List[Identity]:
    """Create countries."""
    countries = []
    for entity in entities:
        country = create_country(entity, author)
        countries.append(country)
    return countries


def create_relationship(
    relationship_type: str,
    author: Identity,
    source: STIXDomainObject,
    target: STIXDomainObject,
    object_marking_refs: List[MarkingDefinition],
    first_seen: datetime,
    last_seen: datetime,
    confidence_level: int,
) -> Relationship:
    """Create a relationship."""
    return Relationship(
        created_by_ref=author,
        relationship_type=relationship_type,
        source_ref=source.id,
        target_ref=target.id,
        object_marking_refs=object_marking_refs,
        custom_properties={
            CustomProperties.FIRST_SEEN: first_seen,
            CustomProperties.LAST_SEEN: last_seen,
            CustomProperties.WEIGHT: confidence_level,
        },
    )


def create_relationships(
    relationship_type: str,
    author: Identity,
    sources: List[STIXDomainObject],
    targets: List[STIXDomainObject],
    object_marking_refs: List[MarkingDefinition],
    first_seen: datetime,
    last_seen: datetime,
    confidence_level: int,
) -> List[Relationship]:
    """Create relationships."""
    relationships = []
    for source in sources:
        for target in targets:
            relationship = create_relationship(
                relationship_type,
                author,
                source,
                target,
                object_marking_refs,
                first_seen,
                last_seen,
                confidence_level,
            )
            relationships.append(relationship)
    return relationships


def create_targets_relationships(
    author: Identity,
    sources: List[STIXDomainObject],
    targets: List[STIXDomainObject],
    object_marking_refs: List[MarkingDefinition],
    first_seen: datetime,
    last_seen: datetime,
    confidence_level: int,
) -> List[Relationship]:
    """Create 'targets' relationships."""
    return create_relationships(
        "targets",
        author,
        sources,
        targets,
        object_marking_refs,
        first_seen,
        last_seen,
        confidence_level,
    )


def create_uses_relationships(
    author: Identity,
    sources: List[STIXDomainObject],
    targets: List[STIXDomainObject],
    object_marking_refs: List[MarkingDefinition],
    first_seen: datetime,
    last_seen: datetime,
    confidence_level: int,
) -> List[Relationship]:
    """Create 'uses' relationships."""
    return create_relationships(
        "uses",
        author,
        sources,
        targets,
        object_marking_refs,
        first_seen,
        last_seen,
        confidence_level,
    )


def create_indicates_relationships(
    author: Identity,
    sources: List[STIXDomainObject],
    targets: List[STIXDomainObject],
    object_marking_refs: List[MarkingDefinition],
    first_seen: datetime,
    last_seen: datetime,
    confidence_level: int,
) -> List[Relationship]:
    """Create 'indicates' relationships."""
    return create_relationships(
        "indicates",
        author,
        sources,
        targets,
        object_marking_refs,
        first_seen,
        last_seen,
        confidence_level,
    )


def create_object_refs(
    *objects: Union[
        STIXDomainObject,
        STIXRelationshipObject,
        List[STIXRelationshipObject],
        List[STIXDomainObject],
    ]
) -> List[STIXDomainObject]:
    """Create object references."""
    object_refs = []
    for obj in objects:
        if isinstance(obj, STIXDomainObject):
            object_refs.append(obj)
        else:
            object_refs.extend(obj)
    return object_refs


def create_tag(entity: Entity, source_name: str, color: str) -> Mapping[str, str]:
    """Create a tag."""
    value = entity.value
    if value is None:
        value = f"NO_VALUE_{entity.id}"

    return {
        "tag_type": source_name,
        "value": value,
        "color": color,
    }


def create_tags(entities: List[Entity], source_name: str) -> List[Mapping[str, str]]:
    """Create tags."""
    color = "#cf3217"

    tags = []
    for entity in entities:
        tag = create_tag(entity, source_name, color)
        tags.append(tag)
    return tags


def remove_html_tags(html_text: str) -> str:
    document = fromstring(html_text)
    text = document.text_content()
    return text.strip()


def create_report(
    name: str,
    description: str,
    published: datetime,
    author: Identity,
    object_refs: List[STIXDomainObject],
    external_references: List[ExternalReference],
    object_marking_refs: List[MarkingDefinition],
    report_status: int,
    report_type: str,
    confidence_level: int,
    tags: List[Mapping[str, str]],
    files: List[Mapping[str, str]],
) -> STIXReport:
    """Create a report."""
    return STIXReport(
        created_by_ref=author,
        name=name,
        description=description,
        published=published,
        object_refs=object_refs,
        labels=["threat-report"],
        external_references=external_references,
        object_marking_refs=object_marking_refs,
        custom_properties={
            CustomProperties.REPORT_CLASS: report_type,
            CustomProperties.OBJECT_STATUS: report_status,
            CustomProperties.SRC_CONF_LEVEL: confidence_level,
            CustomProperties.FILES: files,
            CustomProperties.TAG_TYPE: tags,
        },
    )


def create_stix2_report_from_report(
    report: Report,
    author: Identity,
    object_refs: List[STIXDomainObject],
    external_references: List[ExternalReference],
    object_marking_refs: List[MarkingDefinition],
    report_status: int,
    report_type: str,
    confidence_level: int,
    tags: List[Mapping[str, str]],
    files: List[Mapping[str, str]],
) -> STIXReport:
    """Create a report."""
    # TODO: What to do with the description?
    if report.rich_text_description is not None:
        description = remove_html_tags(report.rich_text_description)
    elif report.description is not None:
        description = report.description
    elif report.short_description is not None:
        description = report.short_description
    else:
        description = "N/A"

    report_created_date = report.created_date
    if report_created_date is None:
        report_created_date = datetime_utc_now()

    return create_report(
        report.name,
        description,
        report_created_date,
        author,
        object_refs,
        external_references,
        object_marking_refs,
        report_status,
        report_type,
        confidence_level,
        tags,
        files,
    )


def split_countries_and_regions(
    entities: List[Entity], author: Identity
) -> Tuple[List[Identity], List[Identity]]:
    target_regions = []
    target_countries = []

    for entity in entities:
        if entity.slug is None or entity.value is None:
            continue

        # Target countries may also contain regions.
        # Use hack to differentiate between countries and regions.
        if len(entity.slug) > 2:
            target_region = create_region(entity, author)
            target_regions.append(target_region)
        else:
            target_country = create_country(entity, author)
            target_countries.append(target_country)

    return target_regions, target_countries


def create_file_from_download(download: Download) -> Mapping[str, str]:
    """Create file mapping from Download model."""
    filename = download.filename
    if filename is None or not filename:
        logger.error("File download missing a filename")
        filename = "DOWNLOAD_MISSING_FILENAME"

    base64_data = base64.b64encode(download.content.read())

    return {
        "name": filename,
        "data": base64_data.decode("utf-8"),
        "mime_type": "application/pdf",
    }
