import app.services.media as media_module
from app.services.media import _contextual_fallback_stories, _dedupe_quality_first_results, _extract_reference_image_urls, _extract_reference_video_urls, _image_candidate_score, _matches_actual_story_subject, _reference_resolution_queries, _result_quality_rank, _story_subjects, _youtube_search_queries, search_story_media, story_allows_interview_or_podcast, story_media_key, story_visual_plan, suggested_clip_range, video_is_usable_broll


def normal_story():
    return {
        "canonical_title": "Resident Evil film breaks franchise box office records",
        "summary": "The new film posted a major opening weekend.",
        "category": "trend",
        "articles": [{"title": "Resident Evil breaks box office records"}],
    }


def test_official_studio_trailer_is_accepted():
    item = {
        "title": "Resident Evil — Official Trailer",
        "channel": "Sony Pictures Entertainment",
        "channel_is_verified": True,
        "height": 2160,
    }
    assert video_is_usable_broll(item, normal_story())


def test_news_package_is_rejected():
    item = {
        "title": "Resident Evil breaks box office record",
        "channel": "ABC News",
        "channel_is_verified": True,
        "height": 1080,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_commentary_and_reaction_are_rejected_even_if_verified():
    item = {
        "title": "Resident Evil Official Trailer Breakdown & Reaction",
        "channel": "Movie Commentary",
        "channel_is_verified": True,
        "height": 2160,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_unverified_reupload_labeled_official_is_rejected():
    item = {
        "title": "Resident Evil Official Trailer",
        "channel": "Random Uploads",
        "channel_is_verified": False,
        "height": 1080,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_interview_is_rejected_for_unrelated_story():
    item = {
        "title": "Actor Full Interview About Resident Evil",
        "channel": "Variety",
        "channel_is_verified": True,
        "height": 1080,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_original_interview_allowed_when_story_is_about_interview():
    story = {
        "canonical_title": "Brad Pitt reveals new details in Variety interview",
        "summary": "The comments were made during a new interview.",
        "category": "celebrities",
        "articles": [{"title": "Brad Pitt discusses the film in new interview"}],
    }
    item = {
        "title": "Brad Pitt Full Interview",
        "channel": "Variety",
        "channel_is_verified": True,
        "height": 1080,
    }
    assert story_allows_interview_or_podcast(story)
    assert video_is_usable_broll(item, story)


def test_interview_queries_only_added_for_interview_story():
    normal_queries = _youtube_search_queries(normal_story())
    assert not any("full interview" in q.lower() or "podcast interview" in q.lower() for q in normal_queries)

    story = {
        "canonical_title": "Actor discusses sequel on Film Talk podcast",
        "summary": "The actor made the comments during the podcast.",
        "category": "celebrities",
        "articles": [],
    }
    queries = _youtube_search_queries(story)
    assert any("podcast interview" in q.lower() for q in queries)


def test_trailer_aggregator_reupload_is_rejected():
    item = {
        "title": "Resident Evil Official Trailer",
        "channel": "IGN",
        "channel_is_verified": True,
        "height": 2160,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_same_studio_but_wrong_movie_is_rejected():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first trailer for Ray Gunn.",
        "category": "upcoming_films",
        "articles": [{"title": "Ray Gunn gets first trailer"}],
    }
    item = {
        "title": "Ladies First | Official Trailer | Netflix",
        "channel": "Netflix",
        "channel_is_verified": True,
        "height": 1080,
        "_search_query": "Ray Gunn official trailer",
    }
    assert not video_is_usable_broll(item, story)


def test_exact_movie_from_original_studio_is_accepted():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first trailer for Ray Gunn.",
        "category": "upcoming_films",
        "articles": [{"title": "Ray Gunn gets first trailer"}],
    }
    item = {
        "title": "Ray Gunn | Official Trailer | Netflix",
        "channel": "Netflix",
        "channel_is_verified": True,
        "height": 1080,
        "_search_query": "Ray Gunn official trailer",
    }
    assert video_is_usable_broll(item, story)


def test_known_reupload_channel_is_rejected_even_when_title_matches():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first trailer for Ray Gunn.",
        "category": "upcoming_films",
        "articles": [],
    }
    item = {
        "title": "RAY GUNN Official Trailer (2026)",
        "channel": "KinoCheck.com",
        "channel_is_verified": True,
        "height": 2160,
        "_search_query": "Ray Gunn official trailer",
    }
    assert not video_is_usable_broll(item, story)


def test_corporate_story_rejects_unrelated_movie_trailer_from_same_studio():
    story = {
        "canonical_title": "Paramount reaches deal with California, other states over Warner merger",
        "summary": "A legal settlement changes the path of the Paramount-Warner merger.",
        "category": "industry",
        "articles": [{"title": "States settle Paramount Warner merger lawsuit"}],
    }
    item = {
        "title": "Dune: Part Three | Official Trailer",
        "channel": "Warner Bros.",
        "channel_is_verified": True,
        "height": 2160,
        "_search_query": "Warner Bros official trailer",
    }
    assert not video_is_usable_broll(item, story)


def test_corporate_story_accepts_company_logo_or_lot_broll():
    story = {
        "canonical_title": "Paramount reaches deal with California, other states over Warner merger",
        "summary": "A legal settlement changes the path of the Paramount-Warner merger.",
        "category": "industry",
        "articles": [{"title": "States settle Paramount Warner merger lawsuit"}],
    }
    item = {
        "title": "Welcome to the Warner Bros. Studio Lot",
        "channel": "Warner Bros.",
        "channel_is_verified": True,
        "height": 2160,
        "_search_query": "Warner Bros official studio lot",
    }
    assert video_is_usable_broll(item, story)


def test_old_franchise_entry_is_rejected_for_current_story():
    story = {
        "canonical_title": "New Resident Evil film breaks franchise box office records",
        "summary": "The new Resident Evil movie opened strongly.",
        "category": "trend",
        "articles": [{"title": "Resident Evil breaks records", "published_at": "2026-09-26"}],
    }
    old_item = {
        "title": "RESIDENT EVIL [2002] - Official Trailer (HD)",
        "channel": "Sony Pictures Entertainment",
        "channel_is_verified": True,
        "height": 1080,
        "upload_date": "20120301",
        "_search_query": "Resident Evil 2026 official trailer",
    }
    assert not video_is_usable_broll(old_item, story)


def test_current_franchise_trailer_is_accepted():
    story = {
        "canonical_title": "New Resident Evil film breaks franchise box office records",
        "summary": "The new Resident Evil movie opened strongly.",
        "category": "trend",
        "articles": [{"title": "Resident Evil breaks records", "published_at": "2026-09-26"}],
    }
    current_item = {
        "title": "RESIDENT EVIL – Official Trailer (4K)",
        "channel": "Sony Pictures Entertainment",
        "channel_is_verified": True,
        "height": 2160,
        "upload_date": "20260515",
        "_search_query": "Resident Evil 2026 official trailer",
    }
    assert video_is_usable_broll(current_item, story)


def test_primary_quoted_title_wins_over_secondary_title():
    story = {
        "canonical_title": "'Avengers: Doomsday': Trailers, tickets, release date and 'Endgame: Encore' details",
        "summary": "The update focuses on Avengers: Doomsday.",
        "category": "trend",
        "articles": [{"title": "Avengers Doomsday update", "published_at": "2026-09-25"}],
    }
    endgame = {
        "title": "Avengers: Endgame Encore | Official Trailer",
        "channel": "IMAX",
        "channel_is_verified": True,
        "height": 1080,
        "upload_date": "20260920",
        "_search_query": "Avengers: Doomsday 2026 official trailer",
    }
    doomsday = {
        "title": "Avengers: Doomsday | Official Trailer",
        "channel": "Marvel Entertainment",
        "channel_is_verified": True,
        "height": 1080,
        "upload_date": "20260920",
        "_search_query": "Avengers: Doomsday 2026 official trailer",
    }
    assert not video_is_usable_broll(endgame, story)
    assert video_is_usable_broll(doomsday, story)


def test_duplicate_ray_gunn_headlines_share_media_key():
    first = {
        "canonical_title": "Brad Bird’s ‘Ray Gunn’ Gets First Trailer, 70mm Theatrical Release, Expanded Voice Cast",
        "summary": "Brad Bird's Ray Gunn received its first trailer.",
        "category": "upcoming_films",
        "articles": [
            {
                "title": "Brad Bird’s ‘Ray Gunn’ Gets First Trailer and a Limited 70mm Theatrical Release - What's on Netflix",
                "published_at": "2026-09-24",
            },
            {
                "title": "Brad Bird’s ‘Ray Gunn’ Gets First Trailer, 70mm Theatrical Release, Expanded Voice Cast - Cartoon Brew",
                "published_at": "2026-09-24",
            },
        ],
    }
    second = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first Ray Gunn trailer.",
        "category": "upcoming_films",
        "articles": [
            {
                "title": "Ray Gunn Trailer: Netflix Sets Theatrical Release With First Look",
                "published_at": "2026-09-24",
            }
        ],
    }
    assert story_media_key(first) == story_media_key(second) == "title:ray gunn"


def test_ray_gunn_search_uses_distributor_when_story_mentions_netflix():
    story = {
        "canonical_title": "Brad Bird’s ‘Ray Gunn’ Gets First Trailer, 70mm Theatrical Release, Expanded Voice Cast",
        "summary": "Brad Bird's Ray Gunn received its first trailer.",
        "category": "upcoming_films",
        "articles": [
            {
                "title": "Brad Bird’s ‘Ray Gunn’ Gets First Trailer and a Limited 70mm Theatrical Release - What's on Netflix",
                "published_at": "2026-09-24",
            }
        ],
    }
    queries = _youtube_search_queries(story)
    assert any("ray gunn netflix official trailer" in q.lower() for q in queries)


def test_reused_video_gets_distinct_clip_ranges():
    first = suggested_clip_range("2:37", 0)
    second = suggested_clip_range("2:37", 1)
    third = suggested_clip_range("2:37", 2)
    assert first == (5, 17)
    assert second == (22, 34)
    assert third == (39, 51)
    assert len({first, second, third}) == 3


def test_short_video_clip_range_stays_inside_duration():
    start, end = suggested_clip_range("0:10", 2)
    assert 0 <= start < end <= 10



def test_reference_page_extracts_embedded_video_urls():
    html = """
    <html><head>
      <meta property="og:video" content="https://cdn.netflix.com/ray-gunn/trailer.mp4">
    </head><body>
      <iframe src="https://www.youtube.com/embed/AbCdEf12345?autoplay=1"></iframe>
      <video><source src="/media/official-trailer.m3u8"></video>
    </body></html>
    """
    urls = _extract_reference_video_urls(html, "https://www.netflix.com/tudum/articles/ray-gunn")
    found = {url for url, _primary in urls}
    assert "https://www.youtube.com/watch?v=AbCdEf12345" in found
    assert "https://cdn.netflix.com/ray-gunn/trailer.mp4" in found
    assert "https://www.netflix.com/media/official-trailer.m3u8" in found


def test_official_direct_video_from_reference_page_can_be_broll():
    story = {
        "canonical_title": "Narnia: The Magician’s Nephew, Directed by Greta Gerwig, Roars to Life in 2027",
        "summary": "Netflix revealed a new look at Narnia: The Magician's Nephew.",
        "category": "upcoming_films",
        "articles": [
            {
                "title": "Narnia: The Magician’s Nephew, Directed by Greta Gerwig, Roars to Life in 2027",
                "source": "Netflix",
                "published_at": "2026-09-25",
            }
        ],
    }
    item = {
        "title": "video",
        "channel": "Netflix",
        "height": 1080,
        "_reference_direct_asset": True,
        "_reference_article_source": "Netflix",
        "_reference_article_title": "Narnia: The Magician’s Nephew, Directed by Greta Gerwig, Roars to Life in 2027",
    }
    assert video_is_usable_broll(item, story)


def test_direct_video_on_news_site_is_not_automatically_official_broll():
    story = {
        "canonical_title": "The Further Mis-Adventures of Cliff Booth trailer released",
        "summary": "The trailer was released this week.",
        "category": "upcoming_films",
        "articles": [{"title": "Cliff Booth trailer released", "source": "Random News"}],
    }
    item = {
        "title": "video",
        "channel": "Random News",
        "height": 1080,
        "_reference_direct_asset": True,
        "_reference_article_source": "Random News",
        "_reference_article_title": "The Further Mis-Adventures of Cliff Booth trailer released",
    }
    assert not video_is_usable_broll(item, story)



def test_official_reference_embed_for_title_named_in_multi_title_story_is_accepted():
    story = {
        "canonical_title": "Weekend Box Office: Avengers: Endgame Encore beats Resident Evil in week two",
        "summary": "The weekend box office compared Avengers: Endgame Encore and Resident Evil.",
        "category": "trend",
        "articles": [
            {
                "title": "Weekend Box Office: Avengers: Endgame Encore beats Resident Evil in week two",
                "source": "JoBlo",
                "published_at": "2026-09-26",
            }
        ],
    }
    item = {
        "title": "Avengers: Endgame Encore | Official Trailer",
        "channel": "IMAX",
        "channel_is_verified": True,
        "height": 1080,
        "upload_date": "20260920",
        "_reference_page_url": "https://example.com/weekend-box-office",
        "_reference_article_source": "JoBlo",
        "_reference_article_title": "Weekend Box Office: Avengers: Endgame Encore beats Resident Evil in week two",
    }
    assert video_is_usable_broll(item, story)



def test_same_video_prefers_4k_over_1080_reference_copy():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first Ray Gunn trailer.",
        "category": "upcoming_films",
        "articles": [{"title": "Ray Gunn gets first trailer", "source": "Deadline"}],
    }
    reference_1080 = {
        "id": "ref",
        "media_type": "video",
        "title": "Ray Gunn | Official Trailer | Netflix",
        "page_url": "https://example.com/embed/ray-gunn",
        "source": "Netflix",
        "provider": "Reference page · official B-roll",
        "duration": "2:37",
        "height": 1080,
    }
    youtube_4k = {
        "id": "yt",
        "media_type": "video",
        "title": "Ray Gunn | Official Trailer | Netflix",
        "page_url": "https://www.youtube.com/watch?v=raygunn4k",
        "source": "Netflix",
        "provider": "YouTube · official B-roll",
        "duration": "2:37",
        "height": 2160,
    }
    ranked = _dedupe_quality_first_results([reference_1080, youtube_4k], story, 12)
    assert ranked[0]["id"] == "yt"
    assert ranked[0]["height"] == 2160


def test_quality_order_is_4k_then_1440_then_1080_then_720():
    story = normal_story()
    items = [
        {"id": "720", "media_type": "video", "title": "Resident Evil Official Trailer", "page_url": "https://x/720", "source": "Sony Pictures Entertainment", "provider": "YouTube · official B-roll", "duration": "2:30", "height": 720},
        {"id": "1080", "media_type": "video", "title": "Resident Evil Official Trailer", "page_url": "https://x/1080", "source": "Sony Pictures Entertainment", "provider": "Reference page · official B-roll", "duration": "2:30", "height": 1080},
        {"id": "1440", "media_type": "video", "title": "Resident Evil Official Trailer", "page_url": "https://x/1440", "source": "Sony Pictures Entertainment", "provider": "Web video · official B-roll", "duration": "2:30", "height": 1440},
        {"id": "2160", "media_type": "video", "title": "Resident Evil Official Trailer", "page_url": "https://x/2160", "source": "Sony Pictures Entertainment", "provider": "YouTube · official B-roll", "duration": "2:30", "height": 2160},
    ]
    ranked = _dedupe_quality_first_results(items, story, 12)
    assert [x["height"] for x in ranked[:4]] == [2160, 1440, 1080, 720]



def test_werwulf_headline_uses_movie_title_not_quoted_slogan():
    story = {
        "canonical_title": "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans",
        "summary": "Robert Eggers released a new trailer for Werwulf.",
        "category": "upcoming_films",
        "articles": [],
    }
    assert _story_subjects(story) == ["Werwulf"]
    queries = _youtube_search_queries(story)
    assert any("werwulf official trailer" in q.lower() for q in queries)


def test_weekend_box_office_headline_extracts_endgame_encore():
    story = {
        "canonical_title": "Weekend Box Office: Avengers: Endgame Encore beats Resident Evil in week two",
        "summary": "Avengers: Endgame Encore led Resident Evil at the box office.",
        "category": "trend",
        "articles": [],
    }
    assert _story_subjects(story) == ["Avengers: Endgame Encore"]


def test_lord_of_the_rings_headline_extracts_title_before_takes():
    story = {
        "canonical_title": "Lord of the Rings takes us back to the Shire in first look at new movie from Andy Serkis",
        "summary": "A first look at the new Lord of the Rings movie was released.",
        "category": "upcoming_films",
        "articles": [],
    }
    assert _story_subjects(story) == ["Lord of the Rings"]


def test_narnia_headline_drops_director_credit_clause():
    story = {
        "canonical_title": "Narnia: The Magician’s Nephew, Directed by Greta Gerwig, Roars to Life in 2027",
        "summary": "Netflix revealed Narnia: The Magician's Nephew.",
        "category": "upcoming_films",
        "articles": [],
    }
    assert _story_subjects(story) == ["Narnia: The Magician’s Nephew"]



def test_zero_result_upcoming_movie_gets_previous_franchise_fallback():
    story = {
        "canonical_title": "Avatar: Fire and Ash reveals a new production update",
        "summary": "The next Avatar movie has no trailer yet.",
        "category": "upcoming_films",
        "articles": [],
    }
    variants = _contextual_fallback_stories(story)
    archive = [(item, kind) for item, kind in variants if kind == "previous installment/franchise"]
    assert archive
    fallback_story, kind = archive[0]
    assert fallback_story["_media_subject_override"] == "Avatar"
    assert fallback_story["_allow_archive_media"] is True
    queries = _youtube_search_queries(fallback_story)
    assert any("avatar official trailer" in q.lower() for q in queries)


def test_actor_or_director_quote_context_gets_person_broll_fallback():
    story = {
        "canonical_title": "Avatar: Fire and Ash production update",
        "summary": "Director James Cameron discusses the film.",
        "_narration_text": 'James Cameron said “we wanted the ocean to feel different this time.”',
        "category": "upcoming_films",
        "articles": [],
    }
    variants = _contextual_fallback_stories(story)
    people = [(item, kind) for item, kind in variants if kind == "cast/director"]
    assert people
    fallback_story, kind = people[0]
    assert fallback_story["_media_subject_override"] == "James Cameron"
    assert fallback_story["_allow_spoken_broll"] is True
    queries = _youtube_search_queries(fallback_story)
    assert any("james cameron interview" in q.lower() for q in queries)


def test_contextual_archive_broll_allows_older_official_franchise_video():
    fallback_story = {
        "canonical_title": "Avatar: Fire and Ash",
        "summary": "No current footage is available.",
        "category": "upcoming_films",
        "_media_subject_override": "Avatar",
        "_allow_archive_media": True,
        "_contextual_kind": "previous installment/franchise",
    }
    old_official = {
        "title": "Avatar | Official Trailer",
        "channel": "20th Century Studios",
        "channel_is_verified": True,
        "height": 2160,
        "upload_date": "20200101",
        "_search_query": "Avatar official trailer 4K",
    }
    assert video_is_usable_broll(old_official, fallback_story)



def test_weekend_box_office_story_requires_two_visual_subjects():
    story = {
        "canonical_title": "Weekend Box Office: Avengers: Endgame Encore beats Resident Evil in week two",
        "summary": "Avengers: Endgame Encore stayed ahead while Resident Evil followed in second place.",
        "_narration_text": "Avengers: Endgame Encore held the top spot. Resident Evil remained close behind in week two.",
        "_voice_duration_seconds": 28.0,
        "category": "trend",
        "articles": [],
    }
    plan = story_visual_plan(story)
    assert plan["subjects"][:2] == ["Avengers: Endgame Encore", "Resident Evil"]
    assert plan["target_count"] >= 2
    assert [beat["label"] for beat in plan["beats"][:2]] == [
        "Avengers: Endgame Encore",
        "Resident Evil",
    ]


def test_longer_single_subject_narration_recommends_multiple_visual_changes():
    story = {
        "canonical_title": "Resident Evil breaks franchise box office records",
        "summary": "The new film opened strongly.",
        "_narration_text": "Resident Evil opened strongly. The film set a new franchise benchmark. Its second weekend remained solid.",
        "_voice_duration_seconds": 31.0,
        "category": "trend",
        "articles": [],
    }
    plan = story_visual_plan(story)
    assert plan["subjects"] == ["Resident Evil"]
    assert plan["target_count"] == 2


def test_quote_story_can_add_director_as_separate_visual_beat():
    story = {
        "canonical_title": "Avatar: Fire and Ash production update",
        "summary": "Director James Cameron discusses the film.",
        "_narration_text": 'James Cameron said “we wanted the ocean to feel different this time.”',
        "_voice_duration_seconds": 26.0,
        "category": "upcoming_films",
        "articles": [],
    }
    plan = story_visual_plan(story)
    labels = [beat["label"] for beat in plan["beats"]]
    assert labels[0] == "Avatar: Fire and Ash production update"
    assert "James Cameron" in labels
    assert plan["target_count"] >= 2



def test_werwulf_visual_plan_does_not_treat_quoted_slogan_as_title():
    story = {
        "canonical_title": "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans",
        "summary": "Robert Eggers released a new trailer for Werwulf.",
        "_narration_text": "Feed upon the flesh of mankind! The new Werwulf trailer shows Robert Eggers' latest horror film.",
        "_voice_duration_seconds": 28.0,
        "category": "upcoming_films",
        "articles": [],
    }
    plan = story_visual_plan(story)
    assert plan["subjects"] == ["Werwulf"]
    assert "Feed upon the flesh of mankind!" not in [beat["label"] for beat in plan["beats"]]
    assert plan["target_count"] == 2


def test_gold_derby_reference_resolution_queries_start_with_publisher_subject():
    article = {
        "title": "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans - Gold Derby",
        "source": "Gold Derby",
        "url": "https://news.google.com/rss/articles/example",
    }
    queries = _reference_resolution_queries(article)
    assert queries[0].lower() == 'site:goldderby.com "werwulf"'
    assert any('"werwulf"' in query.lower() for query in queries)


def test_reference_hd_video_skips_broad_search_for_covered_story(monkeypatch):
    story = {
        "canonical_title": "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans - Gold Derby",
        "summary": "Robert Eggers released a new trailer for Werwulf.",
        "_narration_text": "The new Werwulf trailer is here.",
        "_voice_duration_seconds": 10.0,
        "category": "upcoming_films",
        "articles": [{"title": "Werwulf trailer", "source": "Gold Derby", "url": "https://example.com"}],
    }
    reference = [{
        "id": "ref",
        "media_type": "video",
        "title": "WERWULF | Official Trailer",
        "page_url": "https://www.youtube.com/watch?v=officialwerwulf",
        "asset_url": "https://www.youtube.com/watch?v=officialwerwulf",
        "thumbnail_url": "",
        "source": "Focus Features",
        "provider": "Reference page · official B-roll",
        "duration": "2:30",
        "published_at": "20260926",
        "width": 3840,
        "height": 2160,
        "search_query": "Reference page: Werwulf trailer",
    }]
    monkeypatch.setattr(media_module, "_search_reference_page_videos", lambda *args, **kwargs: (reference, []))
    monkeypatch.setattr(
        media_module,
        "_search_youtube_videos",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("YouTube search should be skipped")),
    )
    monkeypatch.setattr(
        media_module,
        "_search_web_video_sources",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Web search should be skipped")),
    )
    results, errors = search_story_media(story, max_images=3, max_videos=8)
    assert not errors
    assert len(results) == 1
    assert results[0]["coverage_label"] == "Werwulf"
    assert results[0]["coverage_kind"] == "current"



def test_lord_of_rings_tv_series_is_not_current_movie_footage():
    story = {
        "canonical_title": "Lord of the Rings takes us back to the Shire in first look at new movie from Andy Serkis",
        "summary": "A first look at the new Lord of the Rings movie from Andy Serkis was released.",
        "category": "upcoming_films",
        "articles": [{"title": "Lord of the Rings first look at new movie", "published_at": "2026-09-26"}],
    }
    rings_of_power = {
        "title": "The Lord of The Rings: The Rings of Power - Official Teaser Trailer | Prime Video",
        "channel": "Amazon Prime Video UK & IE",
        "channel_is_verified": True,
        "height": 1080,
        "upload_date": "20260701",
        "_search_query": "Lord of the Rings official trailer",
    }
    assert not video_is_usable_broll(rings_of_power, story)

    archive_story = dict(story)
    archive_story["_media_subject_override"] = "Lord of the Rings"
    archive_story["_allow_archive_media"] = True
    archive_story["_contextual_kind"] = "previous installment/franchise"
    assert video_is_usable_broll(rings_of_power, archive_story)


def test_reference_article_image_extracts_og_image_before_web_search_fallback():
    html = """
    <html><head>
      <meta property="og:image" content="https://cdn.example.com/narnia-first-look.jpg">
      <meta name="twitter:image" content="/images/narnia-twitter.jpg">
    </head></html>
    """
    images = _extract_reference_image_urls(html, "https://www.netflix.com/tudum/articles/narnia")
    assert images[0] == "https://cdn.example.com/narnia-first-look.jpg"
    assert "https://www.netflix.com/images/narnia-twitter.jpg" in images



def test_full_official_trailer_ranks_above_4k_title_announcement():
    story = {
        "canonical_title": "The Further Mis-Adventures of Cliff Booth trailer released",
        "summary": "",
        "category": "upcoming_films",
        "articles": [],
    }
    trailer = {
        "title": "THE FURTHER MIS-ADVENTURES OF CLIFF BOOTH | Official Trailer | Netflix",
        "source": "Netflix",
        "provider": "YouTube · official B-roll",
        "height": 2026,
    }
    announcement = {
        "title": "THE FURTHER MIS-ADVENTURES OF CLIFF BOOTH | TITLE ANNOUNCEMENT | NETFLIX",
        "source": "Netflix",
        "provider": "YouTube · studio/distributor B-roll",
        "height": 2160,
    }
    assert _result_quality_rank(trailer, story) > _result_quality_rank(announcement, story)


def test_landscape_4k_still_ranks_above_portrait_poster():
    story = {
        "canonical_title": "Narnia: The Magician's Nephew first look",
        "summary": "",
        "category": "upcoming_films",
        "articles": [],
    }
    landscape = {
        "title": "Narnia The Magician's Nephew official first look still",
        "source": "Netflix",
        "url": "https://netflix.com/narnia",
        "image": "https://cdn.example/narnia-landscape.jpg",
        "width": 3840,
        "height": 2160,
    }
    portrait = {
        "title": "Narnia The Magician's Nephew official poster",
        "source": "TMDB",
        "url": "https://themoviedb.org/narnia",
        "image": "https://cdn.example/narnia-poster.jpg",
        "width": 2000,
        "height": 3000,
    }
    assert _image_candidate_score(landscape, story) > _image_candidate_score(portrait, story)


def test_movie_story_does_not_treat_series_season_as_current_footage():
    story = {
        "canonical_title": "Lord of the Rings takes us back to the Shire in first look at new movie from Andy Serkis",
        "summary": "",
        "category": "upcoming_films",
        "articles": [],
    }
    item = {
        "title": "The Lord of The Rings: The Rings of Power - Season 3 Teaser",
        "description": "",
        "channel": "Prime Video",
        "_search_query": "Lord of the Rings 2026 official trailer",
    }
    assert not _matches_actual_story_subject(item, story)
