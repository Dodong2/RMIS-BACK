from decimal import Decimal

from rest_framework import serializers

from .models import CreativeWorkRecord, IPRecord, PublicationRecord, SenseRankedPublisher

MANAGE_ROLES = ["system_admin", "riuh"]
REPORT_ROLES = ["system_admin", "riuh", "project_leader", "study_leader"]
CREATIVE_WORK_ROLES = REPORT_ROLES + ["project_staff"]


def validate_study_belongs_to_project(attrs, instance):
    project = attrs.get("project", getattr(instance, "project", None))
    study = attrs.get("study", getattr(instance, "study", None))
    if study and project and study.project_id != project.id:
        raise serializers.ValidationError({"study": "Study does not belong to this project."})
    return attrs


def compute_publication_incentive(pub):
    """Cash award per the Manual's R&D Incentive System (Article V), Books and
    Book Chapters / Original Journal Articles table. Returns None if not
    incentive-eligible (e.g. non-indexed journals, conference proceedings —
    both explicitly discontinued/excluded by the Manual)."""
    pt = pub.publication_type

    if pt == "book":
        if pub.sense_publisher_id:
            return Decimal("75000")
        if pub.has_isbn and pub.is_lspu_published:
            return Decimal("15000")
        return None
    if pt == "book_chapter":
        return Decimal("30000") if pub.sense_publisher_id else None
    if pt == "instructional_material":
        return Decimal("5000") if pub.has_isbn else None
    if pt == "journal_article":
        if pub.is_thesis_derived and not pub.is_supervised_approved_thesis:
            return None
        if pub.indexing_tier == "isi":
            if pub.impact_factor is None:
                return None
            if pub.impact_factor >= Decimal("2.00"):
                return Decimal("60000")
            if pub.impact_factor >= Decimal("0.50"):
                return Decimal("50000")
            return Decimal("40000")
        if pub.indexing_tier == "scopus":
            return Decimal("60000") if (pub.h_index or 0) >= Decimal("35.00") else Decimal("40000")
        if pub.indexing_tier == "lspu_refereed":
            return Decimal("5000")
        return None  # non-indexed: incentive discontinued per the Manual
    return None  # conference_proceeding: no monetary incentive per the Manual


def compute_ip_incentive_eligible(ip):
    """Eligibility only (the Manual defers the actual amount to the separate
    IP Policy schedule) — trademarks never qualify; TRL>=4 required unless
    adopted by a recipient community under a notarized MOA."""
    if ip.ip_type == "trademark" or ip.status != "registered" or ip.incentive_claimed:
        return False
    if ip.is_adopted_by_community and ip.adoption_moa_reference:
        return True
    return ip.trl is not None and ip.trl >= 4


class SenseRankedPublisherSerializer(serializers.ModelSerializer):
    class Meta:
        model = SenseRankedPublisher
        fields = ["id", "name", "created_at"]


class PublicationRecordSerializer(serializers.ModelSerializer):
    estimated_incentive = serializers.SerializerMethodField()

    class Meta:
        model = PublicationRecord
        fields = [
            "id", "project", "study", "lead_author", "title", "publication_type", "indexing_tier",
            "impact_factor", "h_index", "sense_publisher", "has_isbn", "is_lspu_published",
            "is_thesis_derived", "is_supervised_approved_thesis", "publisher_name", "doi_or_isbn",
            "published_on", "estimated_incentive", "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]

    def get_estimated_incentive(self, obj):
        return compute_publication_incentive(obj)

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class IPRecordSerializer(serializers.ModelSerializer):
    incentive_eligible = serializers.SerializerMethodField()

    class Meta:
        model = IPRecord
        fields = [
            "id", "project", "study", "creator", "co_creators", "title", "ip_type", "status", "trl",
            "is_commercialization_intended", "is_adopted_by_community", "adoption_moa_reference",
            "registration_number", "registered_on", "incentive_claimed", "incentive_eligible",
            "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]

    def get_incentive_eligible(self, obj):
        return compute_ip_incentive_eligible(obj)

    def validate(self, attrs):
        return validate_study_belongs_to_project(attrs, self.instance)


class CreativeWorkRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreativeWorkRecord
        fields = [
            "id", "project", "creator", "title", "work_type", "description", "date_created",
            "is_registered", "rights_holder", "recorded_by", "created_at",
        ]
        read_only_fields = ["recorded_by"]
