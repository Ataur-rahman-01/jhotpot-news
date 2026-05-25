const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
  BorderStyle, WidthType, ShadingType, PageBreak, PageNumber,
  TabStopType, TabStopPosition,
} = require("docx");

// ── helpers ────────────────────────────────────────────────────────────────
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

const p = (text, opts = {}) => new Paragraph({
  children: [new TextRun({ text, ...opts })],
  spacing: { after: 120 },
});

const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  children: [new TextRun(text)],
});
const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  children: [new TextRun(text)],
});
const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  children: [new TextRun(text)],
});

const code = (text) => new Paragraph({
  children: text.split("\n").map((line, i) => {
    const runs = [];
    if (i > 0) runs.push(new TextRun({ break: 1 }));
    runs.push(new TextRun({ text: line, font: "Courier New", size: 18 }));
    return runs;
  }).flat(),
  shading: { fill: "F4F4F4", type: ShadingType.CLEAR },
  spacing: { before: 120, after: 120 },
  border: {
    top: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD" },
    bottom: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD" },
    left: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD" },
    right: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD" },
  },
});

const bullet = (text) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  children: [new TextRun(text)],
});

const checkItem = (text) => new Paragraph({
  numbering: { reference: "checks", level: 0 },
  children: [new TextRun(text)],
});

const tableCell = (text, opts = {}) => new TableCell({
  borders,
  width: { size: opts.width, type: WidthType.DXA },
  shading: opts.header ? { fill: "1F4E78", type: ShadingType.CLEAR } : undefined,
  margins: { top: 100, bottom: 100, left: 140, right: 140 },
  children: [new Paragraph({
    children: [new TextRun({
      text,
      bold: opts.header || opts.bold,
      color: opts.header ? "FFFFFF" : "000000",
      size: 20,
    })],
  })],
});

// ── content ────────────────────────────────────────────────────────────────
const doc = new Document({
  creator: "BD News Archive",
  title: "Flutter App — Build Tips",
  styles: {
    default: { document: { run: { font: "Calibri", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Calibri", color: "1F4E78" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Calibri", color: "2E75B6" },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Calibri", color: "000000" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "checks", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "☐", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 },
      },
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        children: [new TextRun({ text: "BD News Archive — Flutter Tips", size: 18, color: "888888" })],
        alignment: AlignmentType.RIGHT,
      })] }),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        children: [
          new TextRun({ text: "Page ", size: 18, color: "888888" }),
          new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888" }),
        ],
        alignment: AlignmentType.CENTER,
      })] }),
    },
    children: [
      // ── Title ─────────────────────────────────────────────────────────
      new Paragraph({
        children: [new TextRun({ text: "BD News Archive", size: 56, bold: true, color: "1F4E78" })],
        alignment: AlignmentType.CENTER,
        spacing: { before: 1440, after: 200 },
      }),
      new Paragraph({
        children: [new TextRun({ text: "Flutter App — Build Tips", size: 36, color: "2E75B6" })],
        alignment: AlignmentType.CENTER,
        spacing: { after: 600 },
      }),
      new Paragraph({
        children: [new TextRun({
          text: "Practical guidance for wiring the Flutter Android app to your live Cloud Run API.",
          italics: true, size: 22, color: "555555",
        })],
        alignment: AlignmentType.CENTER,
        spacing: { after: 800 },
      }),

      // ── API Info Box ─────────────────────────────────────────────────
      new Table({
        width: { size: 10080, type: WidthType.DXA },
        columnWidths: [3360, 6720],
        rows: [
          new TableRow({ children: [
            tableCell("API Base URL", { width: 3360, bold: true }),
            tableCell("https://bd-news-api-588230894953.asia-south1.run.app", { width: 6720 }),
          ]}),
          new TableRow({ children: [
            tableCell("Swagger Docs", { width: 3360, bold: true }),
            tableCell("/docs", { width: 6720 }),
          ]}),
          new TableRow({ children: [
            tableCell("Auth", { width: 3360, bold: true }),
            tableCell("Firebase ID Token in Authorization: Bearer header", { width: 6720 }),
          ]}),
          new TableRow({ children: [
            tableCell("Rate limits", { width: 3360, bold: true }),
            tableCell("Per-IP. 429 on exceed. Retry with backoff.", { width: 6720 }),
          ]}),
        ],
      }),

      new Paragraph({ children: [new PageBreak()] }),

      // ── Section 1 ────────────────────────────────────────────────────
      h1("1. API Client — handle 429 and cold starts"),
      p("Cloud Run runs with min-instances=0, so the first request after idle takes 3-5 seconds. The API enforces per-IP rate limits and returns HTTP 429 when exceeded. Wire both into your Dio client with automatic backoff."),
      h3("Add packages"),
      code(`dependencies:
  dio: ^5.4.0
  dio_smart_retry: ^6.0.0`),
      h3("ApiService"),
      code(`// lib/services/api_service.dart
class ApiService {
  static const _baseUrl =
      'https://bd-news-api-588230894953.asia-south1.run.app';

  final _dio = Dio(BaseOptions(
    baseUrl: _baseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 15),  // cold start
  ))..interceptors.add(
    RetryInterceptor(
      dio: Dio(),
      retries: 3,
      retryDelays: [
        const Duration(seconds: 2),
        const Duration(seconds: 4),
        const Duration(seconds: 8),
      ],
      retryEvaluator: (err, _) =>
        err.response?.statusCode == 429 ||
        err.response?.statusCode == 503 ||
        err.type == DioExceptionType.connectionTimeout,
    ),
  );
}`),

      // ── Section 2 ────────────────────────────────────────────────────
      h1("2. Image Loading — never crash on broken URLs"),
      p("Project rule #1 from the architecture: never download images. We only store URL strings (~50 bytes). About 30% of newspaper image URLs break over time, so a graceful placeholder is required."),
      code(`CachedNetworkImage(
  imageUrl: article.imageUrl ?? '',
  fit: BoxFit.cover,
  placeholder: (_, __) => Shimmer.fromColors(
    baseColor: Colors.grey[300]!,
    highlightColor: Colors.grey[100]!,
    child: Container(color: Colors.white),
  ),
  errorWidget: (_, __, ___) => Container(
    color: Colors.grey[200],
    alignment: Alignment.center,
    child: Icon(Icons.newspaper, color: Colors.grey[500], size: 32),
  ),
)`),

      // ── Section 3 ────────────────────────────────────────────────────
      h1("3. Bengali Fonts — required for Bangla articles"),
      p("Default Android system fonts render Bangla poorly. Bundle Noto Sans Bengali (free from Google Fonts) and apply it via your ThemeData."),
      h3("pubspec.yaml"),
      code(`flutter:
  fonts:
    - family: NotoSansBengali
      fonts:
        - asset: assets/fonts/NotoSansBengali-Regular.ttf
        - asset: assets/fonts/NotoSansBengali-Bold.ttf
          weight: 700`),
      h3("Theme"),
      code(`MaterialApp(
  theme: ThemeData(fontFamily: 'NotoSansBengali'),
  // ...
)`),

      // ── Section 4 ────────────────────────────────────────────────────
      h1("4. Cache /sources Aggressively"),
      p("/sources rarely changes and costs 1 hit against your 30/min rate limit. Cache for 24 hours in SharedPreferences."),
      code(`final sourcesProvider = FutureProvider<List<Source>>((ref) async {
  final prefs = await SharedPreferences.getInstance();
  final cached = prefs.getString('sources_cache');
  final cachedAt = prefs.getInt('sources_cached_at') ?? 0;
  final age = DateTime.now().millisecondsSinceEpoch - cachedAt;

  if (cached != null && age < 86400000) {  // 24h
    return parseSources(cached);
  }

  final fresh = await api.getSources();
  await prefs.setString('sources_cache', jsonEncode(fresh));
  await prefs.setInt(
    'sources_cached_at', DateTime.now().millisecondsSinceEpoch,
  );
  return fresh;
});`),

      // ── Section 5 ────────────────────────────────────────────────────
      h1("5. Personalised Feed Pagination"),
      p("GET /feed/{user_id} returns 20 articles. The backend already deduplicates against user_history (compound index on firebase_uid + article_url), so you never need to filter client-side."),
      code(`class FeedNotifier extends StateNotifier<AsyncValue<List<Article>>> {
  FeedNotifier(this.api, this.userId) : super(const AsyncValue.loading()) {
    refresh();
  }
  final ApiService api;
  final String userId;

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    try {
      final feed = await api.getFeed(userId);
      state = AsyncValue.data(feed);
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  Future<void> loadMore() async {
    final current = state.value ?? [];
    final more = await api.getFeed(userId);
    state = AsyncValue.data([...current, ...more]);
  }
}`),

      // ── Section 6 ────────────────────────────────────────────────────
      h1("6. Track Reads — only after 5+ seconds"),
      p("Quick swipes don't mean interest. Start a stopwatch when ArticleScreen opens, send the read event in dispose() only if the user spent at least 5 seconds. Backend uses this to update category and source weights."),
      code(`class _ArticleScreenState extends ConsumerState<ArticleScreen> {
  late final Stopwatch _watch;

  @override
  void initState() {
    super.initState();
    _watch = Stopwatch()..start();
  }

  @override
  void dispose() {
    _watch.stop();
    if (_watch.elapsed.inSeconds >= 5) {
      ref.read(apiProvider).recordRead(
        userId: widget.userId,
        articleId: widget.article.id,
        articleUrl: widget.article.url,
        source: widget.article.source,
        category: widget.article.category,
        tags: widget.article.tags,
        language: widget.article.language,
        duration: _watch.elapsed.inSeconds,
      );
    }
    super.dispose();
  }
}`),

      // ── Section 7 ────────────────────────────────────────────────────
      h1("7. AdMob Placement"),
      p("Don't bury the UX in ads. The four-tier strategy below balances revenue with retention. During development, always use Google's test IDs — switch to your real units only when uploading to Play Store."),
      new Table({
        width: { size: 10080, type: WidthType.DXA },
        columnWidths: [2200, 4380, 1700, 1800],
        rows: [
          new TableRow({ children: [
            tableCell("Ad Type", { width: 2200, header: true }),
            tableCell("Placement", { width: 4380, header: true }),
            tableCell("Frequency", { width: 1700, header: true }),
            tableCell("CPM", { width: 1800, header: true }),
          ]}),
          new TableRow({ children: [
            tableCell("Banner", { width: 2200 }),
            tableCell("Bottom of home_screen.dart, always visible", { width: 4380 }),
            tableCell("Persistent", { width: 1700 }),
            tableCell("Lowest", { width: 1800 }),
          ]}),
          new TableRow({ children: [
            tableCell("Native", { width: 2200 }),
            tableCell("Every 6th item in feed ListView", { width: 4380 }),
            tableCell("In list", { width: 1700 }),
            tableCell("Medium", { width: 1800 }),
          ]}),
          new TableRow({ children: [
            tableCell("Interstitial", { width: 2200 }),
            tableCell("On exit from article_screen.dart", { width: 4380 }),
            tableCell("Max 1/3 articles", { width: 1700 }),
            tableCell("High", { width: 1800 }),
          ]}),
          new TableRow({ children: [
            tableCell("App Open", { width: 2200 }),
            tableCell("After splash on cold launch", { width: 4380 }),
            tableCell("1/session", { width: 1700 }),
            tableCell("Highest", { width: 1800 }),
          ]}),
        ],
      }),
      p(""),
      p("Test Ad Unit IDs (dev only):", { bold: true }),
      code(`Banner       ca-app-pub-3940256099942544/6300978111
Interstitial ca-app-pub-3940256099942544/1033173712
Native       ca-app-pub-3940256099942544/2247696110
App Open     ca-app-pub-3940256099942544/9257395921`),

      // ── Section 8 ────────────────────────────────────────────────────
      h1("8. Bookmarks — store locally too"),
      p("SQLite (sqflite package) for offline access. Sync to backend in a fire-and-forget pattern so the UI stays snappy."),
      code(`// Save locally first (instant UI feedback)
await bookmarksDb.insert('bookmarks', article.toJson(),
    conflictAlgorithm: ConflictAlgorithm.replace);

// Sync to backend, retry later if it fails
api.addBookmark(
  userId: userId,
  articleId: article.id,
  title: article.title,
  imageUrl: article.imageUrl,
  source: article.source,
  category: article.category,
  language: article.language,
).catchError((_) {
  // queue for retry
});`),

      // ── Section 9 ────────────────────────────────────────────────────
      h1("9. Firebase Auth Setup"),
      p("Firebase ID tokens expire after 1 hour. Refresh proactively every 50 minutes to avoid 401s mid-session."),
      code(`// main.dart
await Firebase.initializeApp(
  options: DefaultFirebaseOptions.currentPlatform,
);

// On successful login
final token = await FirebaseAuth.instance.currentUser?.getIdToken();
_dio.options.headers['Authorization'] = 'Bearer $token';

// Refresh every 50 min
Timer.periodic(const Duration(minutes: 50), (_) async {
  final fresh = await FirebaseAuth.instance.currentUser
      ?.getIdToken(true);  // forceRefresh: true
  _dio.options.headers['Authorization'] = 'Bearer $fresh';
});`),

      // ── Section 10 ───────────────────────────────────────────────────
      h1("10. State Management — Riverpod"),
      p("One provider per concern. Auth state changes automatically invalidate downstream providers (feed, bookmarks)."),
      code(`final authProvider = StreamProvider<User?>((ref) =>
    FirebaseAuth.instance.authStateChanges());

final feedProvider = StateNotifierProvider<FeedNotifier,
    AsyncValue<List<Article>>>((ref) {
  final user = ref.watch(authProvider).value;
  if (user == null) throw Exception('Not logged in');
  return FeedNotifier(ref.read(apiProvider), user.uid);
});

final sourcesProvider = FutureProvider<List<Source>>((ref) async {
  // see Section 4 — cached
});

final bookmarksProvider = FutureProvider<List<Article>>((ref) async {
  final local = await bookmarksDb.getAll();
  // optionally merge with server bookmarks
  return local;
});`),

      // ── Recommended Packages ─────────────────────────────────────────
      h1("Recommended Packages"),
      p("Copy into your pubspec.yaml — exact versions tested with Flutter 3.22+ / Dart 3.4."),
      code(`dependencies:
  flutter:
    sdk: flutter

  # API + state
  dio: ^5.4.0
  dio_smart_retry: ^6.0.0
  flutter_riverpod: ^2.5.0

  # Caching + offline
  cached_network_image: ^3.3.0
  shared_preferences: ^2.2.0
  sqflite: ^2.3.0

  # Firebase
  firebase_core: ^2.27.0
  firebase_auth: ^4.17.0
  google_sign_in: ^6.2.0

  # Ads
  google_mobile_ads: ^5.0.0

  # UI
  shimmer: ^3.0.0
  intl: ^0.19.0`),

      // ── Quick Start Checklist ────────────────────────────────────────
      h1("Quick Start Checklist"),
      p("Work through these in order. Each step is independent and verifiable in isolation."),
      checkItem("flutter create bd_news_archive --org com.yourname"),
      checkItem("Add Bengali font (NotoSansBengali) to assets/fonts/"),
      checkItem("Set API_BASE_URL constant to your Cloud Run URL"),
      checkItem("Initialize Firebase + AdMob in main.dart"),
      checkItem("Build login screen (Email + Google Sign-In)"),
      checkItem("Build home (feed) screen — call GET /feed/{user_id}"),
      checkItem("Build article screen — full content + interstitial on exit"),
      checkItem("Build bookmarks screen — SQLite + GET /users/{id}/bookmarks"),
      checkItem("Build profile screen — language pref + sign out"),
      checkItem("Add retry interceptor for 429 / cold-start tolerance"),
      checkItem("Test on a slow connection — feed loads gracefully"),
      checkItem("Replace test AdMob IDs with real ones before Play Store upload"),

      // ── Common Pitfalls ──────────────────────────────────────────────
      h1("Common Pitfalls"),
      bullet("Cold start spikes: don't show 'failed' on first request. Show a shimmer and let the retry interceptor handle it."),
      bullet("Token expiry: if you only refresh on app launch, the user gets logged out after an hour of use. Use the 50-min Timer."),
      bullet("Image overflow: long URLs in CachedNetworkImage without errorWidget will throw — always set both placeholder and errorWidget."),
      bullet("AdMob test IDs in production: triple-check before Play Store release. Real ads only after submission."),
      bullet("Pagination overrun: don't ask for page=1000 — it scans your MongoDB. Backend caps at page<=1000 but be polite."),
      bullet("CORS confusion: it doesn't apply to Flutter apps, only browsers. Your app calls the API directly without CORS."),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("flutter-tips.docx", buf);
  console.log("Wrote flutter-tips.docx (" + buf.length + " bytes)");
});
