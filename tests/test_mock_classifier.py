from src.agent.llm import MockClassifier


def test_mock_classifier_matches_expected_types(items, fixture_rows):
    clf = MockClassifier()
    for item, row in zip(items, fixture_rows):
        c = clf.classify(item)
        assert c.type.value == row["expected"]["type"], item.subject
        assert c.area == row["expected"]["area"], item.subject
