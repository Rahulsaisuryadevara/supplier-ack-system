from supplier_ack.ids import make_id
from supplier_ack.cli import build_parser


def test_make_id_is_stable():
    assert make_id("PO", 123) == "PO-000123"


def test_cli_parser_has_status_command():
    args = build_parser().parse_args(["status"])
    assert args.command == "status"
