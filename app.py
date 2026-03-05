from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response
from flask_pymongo import PyMongo
import certifi # पहिली ओळ
from bson.objectid import ObjectId
from dotenv import load_dotenv
import gridfs
import os
from datetime import datetime

ca = certifi.where()

import cloudinary
import cloudinary.uploader
import os

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# MongoDB configuration
app.config["MONGO_URI"] = os.getenv(
    "MONGO_URI", "mongodb+srv://mindspace:Mindspace2002@cluster0.h3tnstr.mongodb.net/mindspace?retryWrites=true&w=majority"
)

mongo = PyMongo(app, tlsCAFile=ca)
print("Mongo URI:", app.config["MONGO_URI"])
print("Database Name:", mongo.db.name)


# --- Cloudinary Config ---
cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET"),
    secure=True
)

@app.route("/upload_audio", methods=["POST"])
def upload_audio():
    file = request.files["audio"]

    result = cloudinary.uploader.upload(
        file,
        resource_type="video"
    )

    audio_url = result["secure_url"]

    mongo.db.audio.insert_one({
        "audio_url": audio_url
    })

    return "Uploaded Successfully"


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    first_name = request.form.get("first_name", "").strip()
    last_name  = request.form.get("last_name", "").strip()
    email      = request.form.get("email", "").strip()
    phone      = request.form.get("phone", "").strip()
    dob        = request.form.get("dob", "").strip()
    gender     = request.form.get("gender", "").strip()
    city       = request.form.get("city", "").strip()

    # Basic validation
    errors = []
    if not first_name:
        errors.append("First name is required.")
    if not last_name:
        errors.append("Last name is required.")
    if not email:
        errors.append("Email is required.")
    if not phone:
        errors.append("Phone number is required.")

    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("index"))

    # Store form data in session and go to consent screen (do NOT save to DB yet)
    session["pending_user"] = {
        "first_name" : first_name,
        "last_name"  : last_name,
        "full_name"  : f"{first_name} {last_name}",
        "email"      : email,
        "phone"      : phone,
        "dob"        : dob,
        "gender"     : gender,
        "city"       : city,
    }
    return redirect(url_for("consent"))


# ── Consent screen ────────────────────────────────────────
@app.route("/consent", methods=["GET"])
def consent():
    user = session.get("pending_user")
    if not user:
        flash("Session expired. Please fill the form again.", "warning")
        return redirect(url_for("index"))
    return render_template("consent.html", user=user)


@app.route("/agree", methods=["POST"])
def agree():
    agreed = request.form.get("consent_check")
    user   = session.get("pending_user")

    if not user:
        flash("Session expired. Please fill the form again.", "warning")
        return redirect(url_for("index"))

    if not agreed:
        flash("You must agree to the consent to continue.", "warning")
        return redirect(url_for("consent"))

    # Save to MongoDB now that consent is given
    user["consented"]   = True
    user["created_at"]  = datetime.utcnow()
    result = mongo.db.users.insert_one(user)
    session.pop("pending_user", None)
    # Keep user_id in session so the video can be linked to this user
    session["user_id"] = str(result.inserted_id)

    return redirect(url_for("next_page"))


# ── Camera / Video recording page ───────────────────────
@app.route("/next")
def next_page():
    user_id = session.get("user_id")
    if not user_id:
        flash("Session expired. Please start again.", "warning")
        return redirect(url_for("index"))
    return render_template("next.html")


@app.route("/upload-video", methods=["POST"])
def upload_video():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Session expired"}), 403

    video_file = request.files.get("video")
    if not video_file:
        return jsonify({"error": "No video received"}), 400

    # 🔵 Upload to Cloudinary
    video_file.seek(0)
    cloud_result = cloudinary.uploader.upload(
        video_file,
        resource_type="video",
        folder="mindspace/videos"
    )
    cloud_url = cloud_result["secure_url"]

    # 🔵 Upload to GridFS
    video_file.seek(0)
    fs = gridfs.GridFS(mongo.db)
    file_id = fs.put(
        video_file.read(),
        filename=f"{user_id}_recording.webm",
        content_type="video/webm",
        user_id=user_id,
        uploaded_at=datetime.utcnow(),
    )

    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "video_file_id": str(file_id),
            "video_cloud_url": cloud_url,
            "video_uploaded_at": datetime.utcnow()
        }}
    )

    return jsonify({"ok": True, "file_id": str(file_id)})

@app.route("/audio-letters")
def audio_letters():
    user_id = session.get("user_id")
    if not user_id:
        flash("Session expired. Please start again.", "warning")
        return redirect(url_for("index"))
    return render_template("audio_letters.html")

# ── Audio letters page ──────────────────────────────────────
@app.route("/upload-audio-letters", methods=["POST"])
def upload_audio_letters():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Session expired"}), 403

    f = request.files.get("audio")
    if not f:
        return jsonify({"error": "No audio received"}), 400

    # 🔵 Upload to Cloudinary
    f.seek(0)
    cloud_result = cloudinary.uploader.upload(
        f,
        resource_type="video",
        folder="mindspace/audio_letters"
    )
    cloud_url = cloud_result["secure_url"]

    # 🔵 Upload to GridFS
    f.seek(0)
    fs_letters = gridfs.GridFS(mongo.db, collection="audio_letters")
    fid = fs_letters.put(
        f.read(),
        filename=f"{user_id}_letters_all.webm",
        content_type="audio/webm",
        user_id=user_id,

        uploaded_at=datetime.utcnow(),
    )

    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "audio_letters_id": str(fid),
            "audio_letters_cloud_url": cloud_url,
            "audio_letters_at": datetime.utcnow()
        }}
    )

    return jsonify({"ok": True, "file_id": str(fid)})
# ── Audio scenario page ──────────────────────────────────────
SCENARIOS = [
    {
        "id": 1,
        "title": "Lost in a New City",
        "text": "You have just arrived in a new city for the first time and realise you have lost your phone and wallet. You don't know anyone here. Describe what you are feeling right now and explain step by step what you would do to handle this situation.",
    },
    {
        "id": 2,
        "title": "Unexpected Conflict",
        "text": "You are at your workplace and a colleague takes credit for a project you worked very hard on in front of your manager. The manager praises your colleague. Describe how you feel and what you would say or do in response.",
    },
    {
        "id": 3,
        "title": "A Difficult Choice",
        "text": "You have been offered your dream job in another city, but accepting it means leaving your aging parents behind with no one to take care of them. Talk about how you would think through this decision and what you would ultimately choose.",
    },
]

@app.route("/audio-scenario")
def audio_scenario_page():
    user_id = session.get("user_id")
    if not user_id:
        flash("Session expired. Please start again.", "warning")
        return redirect(url_for("index"))

    return render_template("audio_scenario.html", scenario=SCENARIOS[0])


@app.route("/upload-audio-scenario", methods=["POST"])
def upload_audio_scenario():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Session expired"}), 403

    audio_file = request.files.get("audio")
    transcript = request.form.get("transcript", "").strip()
    scenario_id = request.form.get("scenario_id", "").strip()
    scenario_title = request.form.get("scenario_title", "").strip()

    if not audio_file:
        return jsonify({"error": "No audio received"}), 400

    # 🔵 Upload to Cloudinary
    audio_file.seek(0)
    cloud_result = cloudinary.uploader.upload(
        audio_file,
        resource_type="video",
        folder="mindspace/audio_scenario"
    )
    cloud_url = cloud_result["secure_url"]

    # 🔵 Upload to GridFS
    audio_file.seek(0)
    fs_scenario = gridfs.GridFS(mongo.db, collection="audio_scenario")
    file_id = fs_scenario.put(
        audio_file.read(),
        filename=f"{user_id}_scenario.webm",
        content_type="audio/webm",
        user_id=user_id,
        scenario_id=scenario_id,
        scenario_title=scenario_title,
        transcript=transcript,
        uploaded_at=datetime.utcnow(),
    )

    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "audio_scenario_id": str(file_id),
            "audio_scenario_transcript": transcript,
            "audio_scenario_title": scenario_title,
            "audio_scenario_at": datetime.utcnow(),
            "audio_scenario_cloud_url": cloud_url,
        }}
    )

    session.pop("user_id", None)
    return jsonify({"ok": True, "file_id": str(file_id)})
# ── Stream audio files ────────────────────────────────────────
@app.route("/audio-letters/<file_id>")
def stream_audio_letters(file_id):
    try:
        fs  = gridfs.GridFS(mongo.db, collection="audio_letters")
        out = fs.get(ObjectId(file_id))
        return Response(out.read(), mimetype="audio/webm")
    except Exception:
        return "Audio not found", 404


@app.route("/audio-scenario/<file_id>")
def stream_audio_scenario(file_id):
    try:
        fs  = gridfs.GridFS(mongo.db, collection="audio_scenario")
        out = fs.get(ObjectId(file_id))
        return Response(out.read(), mimetype="audio/webm")
    except Exception:
        return "Audio not found", 404


# ── Thank-you page ──────────────────────────────────────────────
@app.route("/thankyou")
def thankyou():
    return render_template("thankyou.html")


# ── Stream a video from GridFS ────────────────────────────
@app.route("/video/<file_id>")
def stream_video(file_id):
    try:
        fs   = gridfs.GridFS(mongo.db)
        grid_out = fs.get(ObjectId(file_id))
        return Response(
            grid_out.read(),
            mimetype=grid_out.content_type or "video/webm",
            headers={"Content-Disposition": "inline"}
        )
    except Exception:
        return "Video not found", 404


# ── Admin: all videos ─────────────────────────────────────
@app.route("/admin/videos")
def admin_videos():
    fs       = gridfs.GridFS(mongo.db)
    files    = list(mongo.db["fs.files"].find().sort("uploadDate", -1))

    # Attach user info to each file
    for f in files:
        uid = f.get("metadata", {}).get("user_id") or f.get("user_id")
        if uid:
            try:
                user = mongo.db.users.find_one({"_id": ObjectId(uid)})
                f["user_info"] = user
            except Exception:
                f["user_info"] = None
        else:
            # try to find user by video_file_id field
            user = mongo.db.users.find_one({"video_file_id": str(f["_id"])})
            f["user_info"] = user

    return render_template("admin_videos.html", files=files)


# ── Admin: delete a video ─────────────────────────────────
@app.route("/admin/videos/delete/<file_id>", methods=["POST"])
def delete_video(file_id):
    try:
        fs = gridfs.GridFS(mongo.db)
        fs.delete(ObjectId(file_id))
        mongo.db.users.update_one(
            {"video_file_id": file_id},
            {"$unset": {"video_file_id": "", "video_uploaded_at": ""}}
        )
        flash("Video deleted.", "info")
    except Exception as e:
        flash(f"Error deleting video: {e}", "danger")
    return redirect(url_for("admin_videos"))


# ── Admin: audio recordings ────────────────────────────────
@app.route("/admin/recordings")
def admin_recordings():
    letters_files  = list(mongo.db["audio_letters.files"].find().sort("uploadDate", -1))
    scenario_files = list(mongo.db["audio_scenario.files"].find().sort("uploadDate", -1))

    def attach_user(files):
        for f in files:
            uid = f.get("user_id")
            try:
                f["user_info"] = mongo.db.users.find_one({"_id": ObjectId(uid)}) if uid else None
            except Exception:
                f["user_info"] = None

    attach_user(letters_files)
    attach_user(scenario_files)
    return render_template("admin_recordings.html",
                           letters_files=letters_files,
                           scenario_files=scenario_files)


@app.route("/admin/recordings/delete-letters/<file_id>", methods=["POST"])
def delete_audio_letters(file_id):
    try:
        fs = gridfs.GridFS(mongo.db, collection="audio_letters")
        fs.delete(ObjectId(file_id))
        flash("Audio deleted.", "info")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("admin_recordings"))


@app.route("/admin/recordings/delete-scenario/<file_id>", methods=["POST"])
def delete_audio_scenario(file_id):
    try:
        fs = gridfs.GridFS(mongo.db, collection="audio_scenario")
        fs.delete(ObjectId(file_id))
        flash("Audio deleted.", "info")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("admin_recordings"))


# ── Admin: delete FULL record (user + all media) ──────────────
@app.route("/admin/delete-record/<user_id>", methods=["POST"])
def delete_full_record(user_id):
    user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        flash("User not found.", "danger")
        return redirect(request.referrer or url_for("users"))

    # Delete video
    if user.get("video_file_id"):
        try:
            gridfs.GridFS(mongo.db).delete(ObjectId(user["video_file_id"]))
        except Exception:
            pass

    # Delete audio letters
    fs_l = gridfs.GridFS(mongo.db, collection="audio_letters")
    for lid in user.get("audio_letters_ids", []):
        try:
            fs_l.delete(ObjectId(lid))
        except Exception:
            pass

    # Delete audio scenario
    if user.get("audio_scenario_id"):
        try:
            gridfs.GridFS(mongo.db, collection="audio_scenario").delete(
                ObjectId(user["audio_scenario_id"])
            )
        except Exception:
            pass

    mongo.db.users.delete_one({"_id": ObjectId(user_id)})
    flash(f"Full record for {user.get('full_name', user_id)} deleted.", "info")
    return redirect(request.referrer or url_for("users"))


# ── Admin: view all users ─────────────────────────────────
@app.route("/users")
def users():
    all_users = list(mongo.db.users.find().sort("created_at", -1))
    return render_template("users.html", users=all_users)


@app.route("/delete/<user_id>", methods=["POST"])
def delete_user(user_id):
    mongo.db.users.delete_one({"_id": ObjectId(user_id)})
    flash("User deleted.", "info")
    return redirect(url_for("users"))


if __name__ == "__main__":
    app.run(debug=True)
