import unittest
from unittest.mock import patch

import pandas as pd

from app.services.qlib_research import QlibResearchService, parse_stock_codes


class QlibResearchTest(unittest.TestCase):
    def test_parse_stock_codes_supports_separators_and_deduplicates(self):
        self.assertEqual(parse_stock_codes("000001, 600000\n000001 300750"), ["000001", "600000", "300750"])

    def test_model_params_are_fixed_to_allowed_values(self):
        params = QlibResearchService._model_params({"num_leaves": 63, "learning_rate": 0.1})
        self.assertEqual(params["num_leaves"], 63)
        self.assertEqual(params["num_boost_round"], 300)
        with self.assertRaises(ValueError):
            QlibResearchService._model_params({"num_leaves": 1})

    def test_features_and_predictions_are_ranked_by_date(self):
        frame = pd.DataFrame([
            {"datetime": "2024-01-02", "instrument": "SZ000001", "close": 10, "volume": 100},
            {"datetime": "2024-01-03", "instrument": "SZ000001", "close": 11, "volume": 120},
            {"datetime": "2024-01-02", "instrument": "SZ000002", "close": 12, "volume": 200},
            {"datetime": "2024-01-03", "instrument": "SZ000002", "close": 11, "volume": 180},
        ])
        features = QlibResearchService._make_features(frame)
        predictions = QlibResearchService._predict(features)
        self.assertEqual(set(predictions["rank"]), {1, 2})
        self.assertEqual(len(predictions), 4)
        self.assertTrue((predictions.groupby("datetime")["rank"].max() == 2).all())

    @patch("app.services.qlib_research.execute_query")
    def test_system_pool_falls_back_to_stock_status(self, execute_query):
        execute_query.return_value = [{"stock_code": "000001"}]
        service = QlibResearchService()
        self.assertEqual(service._system_pool("cn_a"), ["000001"])


if __name__ == "__main__":
    unittest.main()
