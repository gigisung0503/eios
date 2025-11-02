from datetime import datetime
from src.models.db import db

class RawArticle(db.Model):
    __tablename__ = 'raw_articles'
    
    id = db.Column(db.Integer, primary_key=True)
    rss_item_id = db.Column(db.String(255), unique=True, nullable=False)
    original_title = db.Column(db.Text)
    title = db.Column(db.Text)
    translated_description = db.Column(db.Text)
    translated_abstractive_summary = db.Column(db.Text)
    abstractive_summary = db.Column(db.Text)
    combined_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'rss_item_id': self.rss_item_id,
            'original_title': self.original_title,
            'title': self.title,
            'translated_description': self.translated_description,
            'translated_abstractive_summary': self.translated_abstractive_summary,
            'abstractive_summary': self.abstractive_summary,
            'combined_text': self.combined_text,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ProcessedArticle(db.Model):
    __tablename__ = 'processed_articles'
    
    id = db.Column(db.Integer, primary_key=True)
    rss_item_id = db.Column(db.String(255), unique=True, nullable=False)
    extracted_countries = db.Column(db.Text)
    extracted_hazards = db.Column(db.Text)
    risk_signal_assessment = db.Column(db.Text)
    vulnerability_score = db.Column(db.Integer)
    coping_score = db.Column(db.Integer)
    total_risk_score = db.Column(db.Integer)
    is_signal = db.Column(db.String(10))  # 'Yes' or 'No'
    status = db.Column(db.String(20), default='new')  # 'new', 'flagged', 'discarded'
    is_pinned = db.Column(db.Boolean, default=False)  # Whether article was pinned in EIOS
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to raw article
    raw_article_id = db.Column(db.Integer, db.ForeignKey('raw_articles.id'))
    raw_article = db.relationship('RawArticle', backref='processed_article')

    def get_justification(self) -> str:
        """Extract the justification text from the risk assessment field."""
        if not self.risk_signal_assessment:
            return ""
        parts = [p.strip() for p in self.risk_signal_assessment.split("|||")]
        if len(parts) > 2:
            justification_part = parts[2]
            if ':' in justification_part:
                justification_part = justification_part.split(':', 1)[-1]
            return justification_part.strip()
        return ""

    def to_dict(self):
        return {
            'id': self.id,
            'rss_item_id': self.rss_item_id,
            'extracted_countries': self.extracted_countries,
            'extracted_hazards': self.extracted_hazards,
            'risk_signal_assessment': self.risk_signal_assessment,
            'justification': self.get_justification(),
            'vulnerability_score': self.vulnerability_score,
            'coping_score': self.coping_score,
            'total_risk_score': self.total_risk_score,
            'is_signal': self.is_signal,
            'status': self.status,
            'is_pinned': self.is_pinned,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'raw_article': self.raw_article.to_dict() if self.raw_article else None
        }

class UserConfig(db.Model):
    __tablename__ = 'user_config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class ProcessedArticleID(db.Model):
    __tablename__ = 'processed_article_ids'
    
    id = db.Column(db.Integer, primary_key=True)
    rss_item_id = db.Column(db.String(255), unique=True, nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'rss_item_id': self.rss_item_id,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None
        }

