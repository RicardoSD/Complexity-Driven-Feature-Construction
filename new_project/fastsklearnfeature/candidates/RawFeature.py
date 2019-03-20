from fastsklearnfeature.candidates.CandidateFeature import CandidateFeature
from typing import Dict
from typing import Any
from sklearn.preprocessing import FunctionTransformer
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from fastsklearnfeature.candidates.Identity import identity
from fastsklearnfeature.configuration.Config import Config

class RawFeature(CandidateFeature):
    def __init__(self, name, column_id, properties):
        self.name: str = name
        self.column_id: int = column_id
        self.properties: Dict[str, Any] = properties
        self.parents = []
        self.transformation = None

        self.runtime_properties: Dict[str, Any] = {}

        self.pipeline = self.create_pipeline()


    def create_pipeline(self):
        memory=None
        if bool(Config.get_default('pipeline.caching', True)):
            memory="/dev/shm"

        pipeline = Pipeline([
            (
                self.name, ColumnTransformer(
                    [
                        ('identity', FunctionTransformer(identity, validate=False), [self.column_id])
                    ]
                )
            )
        ], memory=memory)
        return pipeline

    def get_transformation_depth(self):
        return 0

    def get_number_of_transformations(self):
        return 0

    def get_number_of_raw_attributes(self):
        return 1

    def get_raw_attributes(self):
        return [self]

    def get_name(self):
        return self.name

    def calculate_traceability(self):
        return 1.0

    def is_numeric(self):
        raw_type = str(self.properties['type'])
        if 'float' in raw_type \
            or 'int' in raw_type \
            or 'bool' in raw_type:
            return True

        return False
