"""
This module contains implementations of different APIs that are used by the
downloader.
"""

import os
import json
import logging
from six import iterkeys
from six.moves.urllib_parse import quote_plus

from six import iteritems

from .utils import BeautifulSoup, make_coursera_absolute_url
from .network import get_page
from .define import (OPENCOURSE_SUPPLEMENT_URL,
                     OPENCOURSE_PROGRAMMING_ASSIGNMENTS_URL,
                     OPENCOURSE_ASSET_URL,
                     OPENCOURSE_ASSETS_URL,
                     OPENCOURSE_API_ASSETS_V1_URL,
                     OPENCOURSE_VIDEO_URL)


class CourseraOnDemand(object):
    """
    This is a class that provides a friendly interface to extract certain
    parts of on-demand courses. On-demand class is a new format that Coursera
    is using, they contain `/learn/' in their URLs. This class does not support
    old-style Coursera classes. This API is by no means complete.
    """

    def __init__(self, session, course_id):
        """
        Initialize Coursera OnDemand API.

        @param session: Current session that holds cookies and so on.
        @type session: requests.Session

        @param course_id: Course ID from course json.
        @type course_id: str
        """
        self._session = session
        self._course_id = course_id

    def extract_links_from_lecture(self,
                                   video_id, subtitle_language='en',
                                   resolution='540p', assets=None):
        """
        Return the download URLs of on-demand course video.

        @param video_id: Video ID.
        @type video_id: str

        @param subtitle_language: Subtitle language.
        @type subtitle_language: str

        @param resolution: Preferred video resolution.
        @type resolution: str

        @param assets: List of assets that may present in the video.
        @type assets: [str]

        @return: @see CourseraOnDemand._extract_links_from_text
        """
        if assets is None:
            assets = []

        links = self._extract_videos_and_subtitles_from_lecture(
            video_id, subtitle_language, resolution)

        assets = self._normalize_assets(assets)
        self._extend_supplement_links(
            links, self._extract_links_from_lecture_assets(assets))

        return links

    def _normalize_assets(self, assets):
        """
        Perform asset normalization. For some reason, assets that are sometimes
        present in lectures, have "@1" at the end of their id. Such "uncut"
        asset id when fed to OPENCOURSE_ASSETS_URL results in error that says:
        "Routing error: 'get-all' not implemented". To avoid that, the last
        two characters from asset id are cut off and after that that method
        works fine. It looks like, Web UI is doing the same.

        @param assets: List of asset ids.
        @type assets: [str]

        @return: Normalized list of asset ids (without trailing "@1")
        @rtype: [str]
        """
        new_assets = []

        for asset in assets:
            # For example: giAxucdaEeWJTQ5WTi8YJQ@1
            if len(asset) == 24:
                # Turn it into: giAxucdaEeWJTQ5WTi8YJQ
                asset = asset[:-2]
            new_assets.append(asset)

        return new_assets

    def _extract_links_from_lecture_assets(self, asset_ids):
        """
        Extract links to files of the asset ids.

        @param asset_ids: List of asset ids.
        @type asset_ids: [str]

        @return: @see CourseraOnDemand._extract_links_from_text
        """
        links = {}

        def _add_asset(name, url, destination):
            filename, extension = os.path.splitext(name)
            if extension is '':
                return

            extension = extension.lower().strip('.')
            basename = os.path.basename(filename)

            if extension not in destination:
                destination[extension] = []
            destination[extension].append((url, basename))

        for asset_id in asset_ids:
            for open_course_asset_id in self._get_open_course_asset_ids(asset_id):
                for asset in self._get_asset_urls(open_course_asset_id):
                    _add_asset(asset['name'], asset['url'], links)

        return links

    def _get_open_course_asset_ids(self, asset_id):
        """
        Get asset ids (sub ids) that are children of the parent asset_id.

        @param asset_id: Asset ID.
        @type asset_id: str

        @return: List of asset IDs.
        @rtype: [str]
        """
        url = OPENCOURSE_ASSETS_URL.format(id=asset_id)
        page = get_page(self._session, url)
        logging.debug('Parsing JSON for asset_id <%s>.', asset_id)
        dom = json.loads(page)

        # Structure is as follows:
        # elements [ {
        #   definition {
        #       assetId
        return [element['definition']['assetId']
                for element in dom['elements']]

    def _get_asset_urls(self, asset_id):
        """
        Get list of asset urls and file names.

        @param asset_id: Asset ID.
        @type asset_id: str

        @return List of dictionaries with asset file names and urls.
        @rtype [{
            'name': '<filename.ext>'
            'url': '<url>'
        }]
        """
        url = OPENCOURSE_API_ASSETS_V1_URL.format(id=asset_id)
        page = get_page(self._session, url)
        dom = json.loads(page)

        # Structure is as follows:
        # elements [ {
        #   name
        #   url {
        #       url
        return [{'name': element['name'],
                 'url': element['url']['url']}
                for element in dom['elements']]

    def _extract_videos_and_subtitles_from_lecture(self,
                                                   video_id,
                                                   subtitle_language='en',
                                                   resolution='540p'):

        url = OPENCOURSE_VIDEO_URL.format(video_id=video_id)
        page = get_page(self._session, url)

        logging.debug('Parsing JSON for video_id <%s>.', video_id)
        video_content = {}
        dom = json.loads(page)

        # videos
        logging.info('Gathering video URLs for video_id <%s>.', video_id)
        sources = dom['sources']
        sources.sort(key=lambda src: src['resolution'])
        sources.reverse()

        # Try to select resolution requested by the user.
        filtered_sources = [source
                            for source in sources
                            if source['resolution'] == resolution]

        if len(filtered_sources) == 0:
            # We will just use the 'vanilla' version of sources here, instead of
            # filtered_sources.
            logging.warn('Requested resolution %s not available for <%s>. '
                         'Downloading highest resolution available instead.',
                         resolution, video_id)
        else:
            logging.info('Proceeding with download of resolution %s of <%s>.',
                         resolution, video_id)
            sources = filtered_sources

        video_url = sources[0]['formatSources']['video/mp4']
        video_content['mp4'] = video_url

        # subtitles and transcripts
        subtitle_nodes = [
            ('subtitles',    'srt', 'subtitle'),
            ('subtitlesTxt', 'txt', 'transcript'),
        ]
        for (subtitle_node, subtitle_extension, subtitle_description) in subtitle_nodes:
            logging.info('Gathering %s URLs for video_id <%s>.', subtitle_description, video_id)
            subtitles = dom.get(subtitle_node)
            if subtitles is not None:
                if subtitle_language == 'all':
                    for current_subtitle_language in subtitles:
                        video_content[current_subtitle_language + '.' + subtitle_extension] = make_coursera_absolute_url(subtitles.get(current_subtitle_language))
                else:
                    if subtitle_language != 'en' and subtitle_language not in subtitles:
                        logging.warning("%s unavailable in '%s' language for video "
                                        "with video id: [%s], falling back to 'en' "
                                        "%s", subtitle_description.capitalize(), subtitle_language, video_id, subtitle_description)
                        subtitle_language = 'en'

                    subtitle_url = subtitles.get(subtitle_language)
                    if subtitle_url is not None:
                        # some subtitle urls are relative!
                        video_content[subtitle_language + '.' + subtitle_extension] = make_coursera_absolute_url(subtitle_url)

        lecture_video_content = {}
        for key, value in iteritems(video_content):
            lecture_video_content[key] = [(value, '')]

        return lecture_video_content

    def extract_links_from_programming(self, element_id):
        """
        Return a dictionary with links to supplement files (pdf, csv, zip,
        ipynb, html and so on) extracted from graded programming assignment.

        @param element_id: Element ID to extract files from.
        @type element_id: str

        @return: @see CourseraOnDemand._extract_links_from_text
        """
        logging.info('Gathering supplement URLs for element_id <%s>.', element_id)

        # Instructions contain text which in turn contains asset tags
        # which describe supplementary files.
        text = ''.join(self._extract_assignment_text(element_id))
        if not text:
            return {}

        supplement_links = self._extract_links_from_text(text)
        return supplement_links

    def extract_links_from_supplement(self, element_id):
        """
        Return a dictionary with supplement files (pdf, csv, zip, ipynb, html
        and so on) extracted from supplement page.

        @return: @see CourseraOnDemand._extract_links_from_text
        """
        logging.info('Gathering supplement URLs for element_id <%s>.', element_id)

        url = OPENCOURSE_SUPPLEMENT_URL.format(
            course_id=self._course_id, element_id=element_id)
        page = get_page(self._session, url)

        dom = json.loads(page)
        supplement_content = {}

        # Supplement content has structure as follows:
        # 'linked' {
        #   'openCourseAssets.v1' [ {
        #       'definition' {
        #           'value'

        for asset in dom['linked']['openCourseAssets.v1']:
            value = asset['definition']['value']
            # Supplement lecture types are known to contain both <asset> tags
            # and <a href> tags (depending on the course), so we extract
            # both of them.
            self._extend_supplement_links(
                supplement_content, self._extract_links_from_text(value))

        return supplement_content

    def _extract_asset_tags(self, text):
        """
        Extract asset tags from text into a convenient form.

        @param text: Text to extract asset tags from.
        @type text: str

        @return: Asset map.
        @rtype: {
            '<id>': {
                'name': '<name>',
                'extension': '<extension>'
            },
            ...
        }
        """
        soup = BeautifulSoup(text)
        asset_tags_map = {}

        for asset in soup.find_all('asset'):
            asset_tags_map[asset['id']] = {'name': asset['name'],
                                           'extension': asset['extension']}

        return asset_tags_map

    def _extract_asset_urls(self, asset_ids):
        """
        Extract asset URLs along with asset ids.

        @param asset_ids: List of ids to get URLs for.
        @type assertn: [str]

        @return: List of dictionaries with asset URLs and ids.
        @rtype: [{
            'id': '<id>',
            'url': '<url>'
        }]
        """
        ids = quote_plus(','.join(asset_ids))
        url = OPENCOURSE_ASSET_URL.format(ids=ids)
        page = get_page(self._session, url)
        dom = json.loads(page)

        return [{'id': element['id'],
                 'url': element['url']}
                for element in dom['elements']]

    def _extract_assignment_text(self, element_id):
        """
        Extract assignment text (instructions).

        @param element_id: Element id to extract assignment instructions from.
        @type element_id: str

        @return: List of assignment text (instructions).
        @rtype: [str]
        """
        url = OPENCOURSE_PROGRAMMING_ASSIGNMENTS_URL.format(
            course_id=self._course_id, element_id=element_id)
        page = get_page(self._session, url)

        dom = json.loads(page)
        return [element['submissionLearnerSchema']['definition']
                ['assignmentInstructions']['definition']['value']
                for element in dom['elements']]

    def _extract_links_from_text(self, text):
        """
        Extract supplement links from the html text. Links may be provided
        in two ways:
            1. <a> tags with href attribute
            2. <asset> tags with id attribute (requires additional request
               to get the direct URL to the asset file)

        @param text: HTML text.
        @type text: str

        @return: Dictionary with supplement links grouped by extension.
        @rtype: {
            '<extension1>': [
                ('<link1>', '<title1>'),
                ('<link2>', '<title2')
            ],
            'extension2': [
                ('<link3>', '<title3>'),
                ('<link4>', '<title4>')
            ],
            ...
        }
        """
        supplement_links = self._extract_links_from_a_tags_in_text(text)

        self._extend_supplement_links(
            supplement_links,
            self._extract_links_from_asset_tags_in_text(text))

        return supplement_links

    def _extract_links_from_asset_tags_in_text(self, text):
        """
        Scan the text and extract asset tags and links to corresponding
        files.

        @param text: Page text.
        @type text: str

        @return: @see CourseraOnDemand._extract_links_from_text
        """
        # Extract asset tags from instructions text
        asset_tags_map = self._extract_asset_tags(text)
        ids = list(iterkeys(asset_tags_map))
        if not ids:
            return {}

        # asset tags contain asset names and ids. We need to make another
        # HTTP request to get asset URL.
        asset_urls = self._extract_asset_urls(ids)

        supplement_links = {}

        # Build supplement links, providing nice titles along the way
        for asset in asset_urls:
            title = asset_tags_map[asset['id']]['name']
            extension = asset_tags_map[asset['id']]['extension']
            if extension not in supplement_links:
                supplement_links[extension] = []
            supplement_links[extension].append((asset['url'], title))

        return supplement_links

    def _extract_links_from_a_tags_in_text(self, text):
        """
        Extract supplement links from the html text that contains <a> tags
        with href attribute.

        @param text: HTML text.
        @type text: str

        @return: Dictionary with supplement links grouped by extension.
        @rtype: {
            '<extension1>': [
                ('<link1>', '<title1>'),
                ('<link2>', '<title2')
            ],
            'extension2': [
                ('<link3>', '<title3>'),
                ('<link4>', '<title4>')
            ]
        }
        """
        soup = BeautifulSoup(text)
        links = [item['href']
                 for item in soup.find_all('a') if 'href' in item.attrs]
        links = sorted(list(set(links)))
        supplement_links = {}

        for link in links:
            filename, extension = os.path.splitext(link)
            # Some courses put links to sites in supplement section, e.g.:
            # http://pandas.pydata.org/
            if extension is '':
                continue

            # Make lowercase and cut the leading/trailing dot
            extension = extension.lower().strip('.')
            basename = os.path.basename(filename)
            if extension not in supplement_links:
                supplement_links[extension] = []
            # Putting basename into the second slot of the tuple is important
            # because that will allow to download many supplements within a
            # single lecture, e.g.:
            # 01_slides-presented-in-this-module.pdf
            # 01_slides-presented-in-this-module_Dalal-cvpr05.pdf
            # 01_slides-presented-in-this-module_LM-3dtexton.pdf
            supplement_links[extension].append((link, basename))

        return supplement_links

    def _extend_supplement_links(self, destination, source):
        """
        Extends (merges) two dictionaries with supplement_links.

        @param destination: Destination dictionary that will be extended.
        @type destination: @see CourseraOnDemand._extract_links_from_text

        @param source: Source dictionary that will be used to extend
            destination dictionary.
        @type source: @see CourseraOnDemand._extract_links_from_text
        """
        for key, value in iteritems(source):
            if key not in destination:
                destination[key] = value
            else:
                destination[key].extend(value)
