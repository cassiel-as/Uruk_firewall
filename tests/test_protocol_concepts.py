import unittest

from services.protocol_concepts import is_protocol_concept_query


class ProtocolConceptTests(unittest.TestCase):
    def test_protocol_constants_and_landauer_are_protocol_concepts(self):
        self.assertTrue(is_protocol_concept_query("LIE_COST係咩？點解係5.85？"))
        self.assertTrue(is_protocol_concept_query("Landauer 係嚴格推導定係比喻？"))

    def test_known_abstract_terms_are_protocol_concepts(self):
        self.assertTrue(is_protocol_concept_query("咩係自由？"))
        self.assertTrue(is_protocol_concept_query("咩係愛？"))
        self.assertTrue(is_protocol_concept_query("what is dignity?"))
        self.assertTrue(is_protocol_concept_query("meaning of truth"))

    def test_ordinary_definition_questions_stay_out(self):
        self.assertFalse(is_protocol_concept_query("What is 2+2?"))
        self.assertFalse(is_protocol_concept_query("What is the capital of France?"))
        self.assertFalse(is_protocol_concept_query("咩係 API？"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
