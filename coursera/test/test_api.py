"""
Test APIs.
"""
import json

import pytest
from mock import patch

from coursera import api

from coursera.test.utils import slurp_fixture


@pytest.fixture
def course():
    course = api.CourseraOnDemand(session=None, course_id='0')
    return course


@patch('coursera.api.get_page')
def test_ondemand_programming_supplement_no_instructions(get_page, course):
    no_instructions = slurp_fixture('json/supplement-programming-no-instructions.json')
    get_page.return_value = no_instructions

    output = course.extract_links_from_programming('0')
    assert {} == output


@patch('coursera.api.get_page')
def test_ondemand_programming_supplement_empty_instructions(get_page, course):
    empty_instructions = slurp_fixture('json/supplement-programming-empty-instructions.json')
    get_page.return_value = empty_instructions

    output = course.extract_links_from_programming('0')
    assert {} == output


@patch('coursera.api.get_page')
def test_ondemand_programming_supplement_one_asset(get_page, course):
    one_asset_tag = slurp_fixture('json/supplement-programming-one-asset.json')
    one_asset_url = slurp_fixture('json/asset-urls-one.json')
    asset_json = json.loads(one_asset_url)
    get_page.side_effect = [one_asset_tag, one_asset_url]

    expected_output = {'pdf': [(asset_json['elements'][0]['url'],
                               'statement-pca')]}
    output = course.extract_links_from_programming('0')
    assert expected_output == output


@patch('coursera.api.get_page')
def test_ondemand_programming_supplement_three_assets(get_page, course):
    three_assets_tag = slurp_fixture('json/supplement-programming-three-assets.json')
    three_assets_url = slurp_fixture('json/asset-urls-three.json')
    get_page.side_effect = [three_assets_tag, three_assets_url]

    expected_output = json.loads(slurp_fixture('json/supplement-three-assets-output.json'))
    output = course.extract_links_from_programming('0')
    output = json.loads(json.dumps(output))
    assert expected_output == output


@patch('coursera.api.get_page')
def test_extract_links_from_lecture_assets(get_page, course):
    open_course_assets_reply = slurp_fixture('json/supplement-open-course-assets-reply.json')
    api_assets_v1_reply = slurp_fixture('json/supplement-api-assets-v1-reply.json')
    get_page.side_effect = [open_course_assets_reply, api_assets_v1_reply]

    expected_output = json.loads(slurp_fixture('json/supplement-extract-links-from-lectures-output.json'))
    assets = ['giAxucdaEeWJTQ5WTi8YJQ']
    output = course._extract_links_from_lecture_assets(assets)
    output = json.loads(json.dumps(output))
    assert expected_output == output
