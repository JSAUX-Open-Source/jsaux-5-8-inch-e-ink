import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GameConnectionCandidateLayoutTests(unittest.TestCase):
    def test_connection_candidate_keeps_identity_and_battery_clear_of_the_toggle(self):
        source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")
        page_start = source.index("const renderConnectionPage = () => {")
        candidate_start = source.index("visibleDeviceCandidates.map((candidate) => {", page_start)
        candidate_end = source.index("            ]);", candidate_start)
        candidate = source[candidate_start:candidate_end]

        self.assertIn(
            'key: "candidate-signal", style: { width: "44px", flex: "0 0 44px", marginLeft: "0"',
            candidate,
        )
        self.assertIn(
            'key: "candidate-details", style: { display: "flex", flexDirection: "column", justifyContent: "center", marginLeft: "16px", flex: "1 1 auto", minWidth: 0 }',
            candidate,
        )
        self.assertIn(
            'key: "name", style: { ...styles.rowValue, fontSize: "11px", lineHeight: 1.2, fontWeight: 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }',
            candidate,
        )
        self.assertIn(
            'key: "address", style: { ...styles.path, fontSize: "10px", lineHeight: 1.2, whiteSpace: "nowrap" }',
            candidate,
        )
        self.assertLess(candidate.index('key: "name"'), candidate.index('key: "address"'))
        self.assertIn(
            'key: "battery", className: "candidate-battery", style: { ...styles.path, fontSize: "11px", marginLeft: "3ch", whiteSpace: "nowrap", flex: "0 0 auto" }',
            candidate,
        )
        self.assertIn(
            'style: { ...styles.toggle(candidateConnected, candidateBusy), width: "36px", flex: "0 0 36px", marginLeft: "12px" }',
            candidate,
        )

    def test_connected_candidate_reuses_the_current_status_battery(self):
        source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")
        page_start = source.index("const renderConnectionPage = () => {")
        candidate_list_start = source.index("const connectedCandidate", page_start)
        candidate_list_end = source.index('        return h("div"', candidate_list_start)
        candidate_list = source[candidate_list_start:candidate_list_end]

        self.assertIn(
            "const connectedCandidate = deviceCandidates.find((candidate) => canonicalMacAddress(candidate?.address) === confirmedConnectedMac);",
            candidate_list,
        )
        self.assertIn("battery,", candidate_list)

    def test_connection_toggle_uses_the_compact_requested_width(self):
        source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")
        page_start = source.index("const renderConnectionPage = () => {")
        candidate_start = source.index("visibleDeviceCandidates.map((candidate) => {", page_start)
        candidate_end = source.index("            ]);", candidate_start)
        candidate = source[candidate_start:candidate_end]

        self.assertIn(
            'style: { ...styles.toggle(candidateConnected, candidateBusy), width: "36px", flex: "0 0 36px", marginLeft: "12px" }',
            candidate,
        )


if __name__ == "__main__":
    unittest.main()
