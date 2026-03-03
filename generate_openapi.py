"""
OpenAPI JSON 파일 생성 스크립트

사용법:
    python generate_openapi.py

Postman / API Dog에서 import할 수 있는 openapi.json 파일을 생성합니다.
FastAPI + Pydantic v2는 OpenAPI 3.1.0을 생성하지만,
Postman·API Dog 호환을 위해 3.0.3으로 자동 다운그레이드합니다.
"""

import copy
import json

from app.main import app


def downgrade_schema_to_3_0(schema: dict) -> dict:
    """OpenAPI 3.1.0 스키마를 3.0.3 호환으로 변환한다."""
    schema = copy.deepcopy(schema)

    # 1) 버전 다운그레이드
    schema["openapi"] = "3.0.3"

    # 2) 재귀적으로 3.1.0 전용 키워드 변환
    _walk(schema)

    return schema


def _walk(node):
    """JSON 트리를 순회하며 3.1.0 → 3.0.3 비호환 요소를 변환."""
    if isinstance(node, dict):
        # "examples" (배열) → "example" (단일 값)  — 스키마 레벨
        if "examples" in node and isinstance(node["examples"], list):
            if node["examples"]:
                node["example"] = node["examples"][0]
            del node["examples"]

        # anyOf 에 null 타입 포함 → nullable로 변환
        if "anyOf" in node:
            types = node["anyOf"]
            non_null = [
                t for t in types
                if t != {"type": "null"} and t.get("type") != "null"
            ]
            has_null = len(non_null) < len(types)
            if has_null and len(non_null) == 1:
                node.update(non_null[0])
                node["nullable"] = True
                del node["anyOf"]

        # const → enum 변환
        if "const" in node:
            node["enum"] = [node.pop("const")]

        # 3.1.0의 type 배열 → nullable 처리
        if isinstance(node.get("type"), list):
            types = node["type"]
            if "null" in types:
                non_null = [t for t in types if t != "null"]
                node["type"] = non_null[0] if len(non_null) == 1 else non_null
                node["nullable"] = True
            else:
                node["type"] = types[0] if len(types) == 1 else types

        for value in node.values():
            _walk(value)

    elif isinstance(node, list):
        for item in node:
            _walk(item)


def main():
    schema_31 = app.openapi()
    schema_30 = downgrade_schema_to_3_0(schema_31)

    output_path = "openapi.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema_30, f, ensure_ascii=False, indent=2)

    print(f"OpenAPI spec generated: {output_path}")
    print(f"  OpenAPI:  {schema_30.get('openapi')}")
    print(f"  Title:    {schema_30.get('info', {}).get('title')}")
    print(f"  Paths:    {list(schema_30.get('paths', {}).keys())}")
    print()
    print("Import 방법:")
    print("  Postman:  File → Import → openapi.json 선택")
    print("  API Dog:  프로젝트 → Import → OpenAPI/Swagger → openapi.json 선택")


if __name__ == "__main__":
    main()
