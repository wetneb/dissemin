/* This is the central Dissemin JavaScript library */
/* Every function should be inside this file */


/* ***
 * Miscellaneous
 * *** */

/* On AJAX errors, we like to be informed via Sentry. If Sentry is not configured, we error to the console */
$(document).ajaxError( function (event, xhr, ajaxSettings, thrownError) {
    try {
        Sentry.captureMessage(thrownError || xhr.statusText, {
            extra: {
                type: ajaxSettings.type,
                url: ajaxSettings.url,
                data: ajaxSettings.data,
                status: xhr.status,
                error: thrownError || xhr.statusText,
                response: xhr.responseText.substring(0, 100)
            }
        });
    }
    catch (e)
    {
        console.error(thrownError);
        console.error(xhr.responseText);
        console.error(ajaxSettings);
    }
});

/* Filter methods that need no csrf protection */
function csrfSafeMethod(method) {
    // these HTTP methods do not require CSRF protection
    return (/^(GET|HEAD|OPTIONS|TRACE)$/.test(method));
}

/* For certain requests like POST we need an csrf token. We insert it */
$(document).ajaxSend( function(event, xhr, settings) {
    if (!csrfSafeMethod(settings.type) && !this.crossDomain) {
        xhr.setRequestHeader("X-CSRFToken", getCookie("csrftoken"));
    }
});

/* Enable bootstrap tooltip */
$(function () {
    $("[data-toggle='tooltip']").tooltip();
});

/* Returns the current csrf token from the cookie. This is the recommend method by django: https://docs.djangoproject.com/en/2.2/ref/csrf/#ajax */
function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        var cookies = document.cookie.split(";");
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            // Does this cookie string begin with the name we want?  if (cookie.substring(0, name.length + 1) === (name + '=')) {
            cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
            break;
        }
    }
    return cookieValue;
}


/* ***
 * Navigation
 * *** */

/* When changing language in dropdown, submit the form */
$(function() {
    $("#select-language").change(function() {
        $("#select-language").submit();
    });
});

/* This is the ORCID Logout. Pass the orcid_base_domain as parameter */
function orcidLogout (orcidBaseDomain) {
    $.ajax({ url: "https://" + orcidBaseDomain + "/userStatus.json?logUserOut=true",
        dataType: "jsonp",
        success: function(result,status,xhr) {
                    window.location.href = Urls["account_logout"]();
                },
        error: function (xhr, status, error) {
                    window.location.href = Urls["account_logout"]();
                }
    });
}


/* ***
 * Paper
 * *** */

/* A paper can have many authors. This functions shows or hides all authors using flex and aria-hidden */
$(function() {
    $("#showAllAuthors").click(function() {
        $("#authorListInteresting").addClass("d-none"); // Hide from screen
        $("#authorListInteresting").attr("aria-hidden", "true"); // Hide from screenreader

        $("#authorListFull").removeClass("d-none"); // Show
        $("#authorListFull").attr("aria-hidden", "false"); // Hide no longer from screenreader
    });

    $("#showInterestingAuthors").click(function() {
        $("#authorListFull").addClass("d-none"); // Hide from screen
        $("#authorListFull").attr("aria-hidden", "true"); // Hide from screenreader

        $("#authorListInteresting").removeClass("d-none"); // Show
        $("#authorListInteresting").attr("aria-hidden", "false"); // Hide no longer from screenreader
    });

});

/* Add item to the to-do list and change UI accordingly
 * This function is here, because it is related to the search */
$(function() {
    $("#paperButtonTodoList").click(function() {
        var obj = $(this);
        var paperPk = obj.attr("data-paper-pk");
        var ajaxUrl = Urls["ajax-todolist-add"]();

        $.ajax({
            data: {
                "paper_pk": paperPk,
            },
            dataType: "json",
            error: function (xhr) {
                obj.text(xhr.responseJSON["error_msg"]);
            },
            method : 'post',
            success: function (data) {
                obj.remove();
                $("#paperTodoListAdded").removeClass("d-none"); // Show
                $("#paperTodoListAdded").attr("aria-hidden", "false"); // Hide no longer from screenreader
            },
            timeout : 5000,
            url : ajaxUrl
        });

    });
});


/* ***
 * Publishers
 * *** */

/* Change the OA status of a publisher */
$(function() {
    $("#changePublisherOAStatus input").change(function() {
        var form = $("#changePublisherOAStatus");

        var ajaxUrl= Urls[form.attr("data-ajax-url")]();
        var publisherPk = form.attr("data-publisher-pk");
        var newStatus = $("input[name=radioOAStatus]:checked", "#changePublisherOAStatus").val();
        var data = {
            "pk" : publisherPk,
            "status" : newStatus
        };

        $.ajax({
            data : data,
            dataType : "text",
            error : function( xhr) {
                alert("Error: " + xhr.responseText);
            },
            method : "POST",
            timeout : 5000,
            url : ajaxUrl
        });
    });
});


/* ***
 * Search
 * *** */

/* Our strategy is: Reload a part of the page and insert any messages that get delivered */

function updateSearch (ajaxUrl, data=null, new_browser_url=false) {
    // slighty fade current results that are going to be replaced
    $("#paperSearchResults").css("opacity", "0.5");
    // turn bird on
    $("#paperSearchWaitingArea").toggleClass("d-none d-flex");

    // call with ajax. it's easy
    $.ajax ({
        contentType : "application/json",
        data : data,
        dataType : "json",
        method : "GET",
        success : function (result) {
            $("#paperSearchResults").html(result.listPapers);
            $("#searchNotifications").html(result.messages);
            // update pie
            updateStats(result.stats);
            // update number of search results
            $("#nbPapersFound").text(
                interpolate(
                    ngettext(
                        "%s paper found",
                        "%s papers found",
                        result.nb_results
                    ),
                    [formatNumbersThousands(result.nb_results)]
                )
            );
            if (new_browser_url === true) {
                window.history.pushState(result, "", "?" + jQuery.param(data));
            }
        },
        timeout : 5000, // 5 seconds
        url : ajaxUrl
    }).done(function() {
        // turn bird off
        $("#paperSearchWaitingArea").toggleClass("d-none d-flex");
        // remove opacity
        $("#paperSearchResults").css("opacity", "");
    });
}

/* If filter by OA status, we immediately refresh the results, otherwise the user needs to confirm */
/* Instant filtering */
$(function () {
    $("#searchByStatus").on("change", function(e) {
        e.preventDefault();
        // Fetch necessary data
        var obj = $("#searchPapers");
        var ajaxUrl =  obj.attr("data-ajax-url"); // We take the url from data-ajax-url since it depends on the view
        var data = obj.serializeArray();

        updateSearch(ajaxUrl, data, true);
    });
});

/* Prevent standard behaviour of form and execute some JS */
$(function () {
    $("#searchPapers").submit(function (e) {
        e.preventDefault();
        // Fetch necessary data
        var obj = $("#searchPapers");
        var ajaxUrl =  obj.attr("data-ajax-url"); // We take the url from data-ajax-url since it depends on the view
        var data = obj.serializeArray();

        updateSearch(ajaxUrl, data, true);
    });
});


/* Refreshes the profil of a user from ORCID.
 * This function is here, because it is related to the search */
$(function () {
    $("#refetchPublications").submit( function () {
        var obj = $(this);
        var researcherPk = obj.attr("data-researcher-pk");
        var ajaxUrl = Urls["refetch-researcher"](researcherPk);

        updateSearch(ajaxUrl);
    });
});

/* When a message on search is closed, move it from inbox toarchive to not display it again
 * This function is here, because it is related to the search */
$(function () {
    $(".messageAlert").on("closed.bs.alert", function () {
        var obj = $(this);
        var messagePk = obj.attr("data-message-pk");
        var url = Urls["inbox-read"](messagePk);

        $.ajax({
            method : "POST",
            url : url
        });
    });
});

/* Claim and unclaim items to or from profile
 * This function is here, because it is related to the search */

$(function () {
    $(".buttonClaimUnclaim").submit( function () {
        var obj = $(this);
        var paperPk = obj.attr("data-pk");
        var action = obj.attr("data-action");
        var fadeout = obj.attr("data-fadeout");

        var ajaxUrl;

        if (action == "claim") {
            obj.text(gettext("Claiming..."));
            ajaxUrl = Urls["ajax-claimPaper"]();
        }
        else if (action == "unclaim") {
            obj.text(gettext("Unclaiming..."));
            ajaxUrl = Urls["ajax-unclaimPaper"]();
        }
        else {
            // action currently ongoing
            return
        }

        $.ajax({
            method : "post",
            data : {
                "pk" : paperPk,
            },
            dataType : "json",
            error : function () {
                if (action == "claim") {
                    obj.text(gettext("Claiming failed!"));
                }
                else {
                    obj.text(gettext("Unclaiming failed!"));
                }
            },
            success : function (data) {
                if (action == "claim") {
                    obj.text(gettext("Exclude from my profile"));
                    obj.attr("data-action", "unclaim");
                }
                else {
                    obj.text(gettext("Include in my profile"));
                    obj.attr("data-action", "claim");
                    if (fadeout == "true") {
                        $("#paper-" + paperPk).fadeOut(300, function() { obj.remove(); });
                    }
                }
            },
            url : ajaxUrl
        });

    });
});

/* Add and remove items to or from the to-do list 
 * This function is here, because it is related to the search */
$(function () {
    $(".buttonTodoList").submit(function () {
        var obj = $(this);
        var action = $(this).attr("data-action");
        var paperPk = $(this).attr("data-pk");
        var fadeout = $(this).attr("data-fadeout");

        var ajaxUrl;

        if (action == "mark") {
            obj.text(gettext("Adding to to-do list"));
            ajaxUrl = Urls["ajax-todolist-add"]();
        }
        else if (action == "unmark") {
            obj.text(gettext("Removing from to-do list"));
            ajaxUrl = Urls["ajax-todolist-remove"]();
        }
        else {
            // action currently ongoing
            return
        }

        $.ajax({
            method: "post",
            url: ajaxUrl,
            data: {
                "paper_pk": paperPk,
            },
            dataType: "json",
            success: function (data) {
                obj.text(data["success_msg"]);
                action = data["data-action"];
                /* If object was removed, i.e. server returned 'mark' and fadeout is true, do fadeout */
                if (action == "mark" && fadeout == "true") {
                    $("#paper-" + paperPk).fadeOut(300, function() { obj.remove(); });
                }
                obj.attr("data-action", action);
            },
            error: function (xhr) {
                obj.text(xhr.responseJSON["error_msg"]);
            }
        });
    });
});


/* ***
 * Statistic
 * *** */

/* Setting colors for the pie */
var stats_colors = ["#FCD206", "#B9C909", "#419BE8", "#dddddd", "#122B52"];
var stats_colors_aggregated = ["#43A000", "#DB1456"];

/* Instead of the full number, which has a lot of digits, we use abbreviations */
function readablizeNumber (number) {
    var units = ['', 'K', 'M', 'G', 'T', 'P'];
    var e = Math.floor(Math.log(number) / Math.log(1000));
    return Math.round((number / Math.pow(1000, e))) + " " + units[e];
}

/* Preprocessing Data */
function preProcessData(data) {
    // The pie only shows active OA categories, which have graph_value = value, while inactive ones have graph_value = 0.
    data.aggregated[0].graph_value = data.aggregated[1].graph_value = 0
    for (var i = 0; i < 5; i++) {
        detail = data.detailed[i]
        detail.graph_value = 0
        if (data.on_statuses.length === 0 || -1 !== $.inArray(detail.id, data.on_statuses)) {
            var j = i < 2 ? 0 : 1
            data.aggregated[j].graph_value += detail.value
            detail.graph_value = detail.value
        }
    }
    // Avoid division by zero when there are no results.
    data.num_tot = data.aggregated[0].graph_value + data.aggregated[1].graph_value
    if (data.num_tot === 0) {
        data.detailed[3].dummy = 1
        data.aggregated[1].dummy = 1
    }
}

/* Showing the Pie itself, which is rendered with d3js */
function showStatsPie (data, chart_id, legend_id) {
    preProcessData(data)

    var detailed_data = data.detailed
    var aggregated_data = data.aggregated
    var w = 201, h = 145;
	var r = 100, mr = 50, imr = 45, ir = 40; // radii
    var color = d3.scale.ordinal().range(stats_colors);
    var color_agg = d3.scale.ordinal().range(stats_colors_aggregated);

	// Create the svg element

    var vis = d3.select("#"+chart_id)
        .append("svg:svg")
            .attr("width", w)
            .attr("height", h)
        .append("svg:g")
            .attr("transform", "translate(" + r + "," + r + ")"); //move the center of the pie chart from 0, 0 to radius, radius

	var parts = vis.selectAll("g.chart")
		.data([detailed_data, aggregated_data])
		.enter()
			.append("svg:g")
				.attr("class", "chart");

	// Outer detailed statistics

    var arc = d3.svg.arc() //this will create <path> elements for us using arc data
        .outerRadius(r)
		.innerRadius(mr);

    var pie = d3.layout.pie() //this will create arc data for us given a list of values
        .value(function(d) { return d.dummy || d.graph_value; }) //we must tell it out to access the value of each element in our data array
		.sort(null)
		.startAngle(-Math.PI/2)
		.endAngle(Math.PI/2);

    var arcs = d3.select(parts[0][0]).selectAll("g.slice") //this selects all <g> elements with class slice (there aren't any yet)
        .data(pie) //associate the generated pie data (an array of arcs, each having startAngle, endAngle and value properties)
        .enter() //this will create <g> elements for every "extra" data element that should be associated with a selection. The result is creating a <g> for every object in the data array
            .append("svg:g") //create a group to hold each slice (we will have a <path> and a <text> element associated with each slice)
                .attr("class", "slice") //allow us to style things in the slices (like text)
            .each(function(d) { this._current = d.value; });

    var paths = arcs.append("svg:path")
                .attr("fill", function(d, i) { return color(i); } ) //set the color for each slice to be chosen from the color function defined above
                .attr("d", arc); //this creates the actual SVG path using the associated data (pie) with the arc drawing function

	// Outer labels
    function translateText(thisArc, d) {
        //set the label's origin to the center of the arc
        //we have to make sure to set these before calling arc.centroid
        d.innerRadius = mr;
        d.outerRadius = r;
        return "translate(" + thisArc.centroid(d) + ")";//this gives us a pair of coordinates like [50, 50]
    }
    function textForLabel(d, i) {
         return (d.data.graph_value === 0 ? "" : readablizeNumber(d.data.graph_value));
    }
	var arcs_text = d3.select(parts[0][0]).selectAll()
        .data(pie)
        .enter()
        .append("svg:g")
        .attr("class", "statsSliceNumber");

    arcs_text.append("svg:text") //add a label to each slice
            .attr("transform", function(d) { return translateText(arc,d); })
            .attr("text-anchor", "middle") //center the text on it's origin
            .text(textForLabel);

	// Inner aggregated statistics

	var arc2 = d3.svg.arc()
        .outerRadius(imr)
		.innerRadius(ir);

	var arcs2 = d3.select(parts[0][1]).selectAll("g.slice")
        .data(pie)
        .enter()
        .append("svg:g")
        .attr("class", "slice");

    arcs2.append("svg:path")
        .attr("fill", function(d, i) { return color_agg(i); } )
        .attr("d", arc2);


	var arcs2_text = d3.select(parts[0][1]).selectAll()
        .data(pie)
        .enter()
        .append("svg:g")
        .attr("class", "statsSliceLegend");

    function lineX(d,i) {
        return arc2.centroid(d)[0];
    }
    function lineY1(d,i) {
        return arc2.centroid(d)[1]+5;
    }
    function lineY2(d,i) {
        return 2 + i*20;
    }
    function hideZero(d) {
        return d.data.graph_value ? null : "none"
    }
    arcs2_text.append("svg:line")
        .attr("x1", lineX)
        .attr("x2", lineX)
        .attr("y1", lineY1)
        .attr("y2", lineY2)
        .attr("style", "stroke:rgb(0,0,0);stroke-width:1");

    arcs2_text.style("display", hideZero)

    function transformAggregatedText(d, i) {
        d.innerRadius = 0;
        d.outerRadius = r/2;
        return "translate(" + arc2.centroid(d)[0] + ", "+ (15 + i*20) +")";
    }
    arcs2_text.append("svg:text")
        .attr("transform", transformAggregatedText)
        .attr("text-anchor", "middle")
        .text(function(d, i) { return aggregated_data[i].label });

	var captions = d3.select("#"+legend_id)

    function updatePie(data) {
        preProcessData(data)

        var arcs = d3.select(parts[0][0]).datum(data.detailed)
        var arcs2 = d3.select(parts[0][1]).datum(data.aggregated)
        var selectArcs = function(elt) { return arcs.selectAll(elt).data(pie).transition() }
        var selectArcs2 = function(elt) { return arcs2.selectAll(elt).data(pie).transition() }

        selectArcs("path")
            .attr("d", arc);
        selectArcs("text")
            .attr("transform",function(d) { return translateText(arc,d) })
            .text(textForLabel);
        selectArcs2("g.statsSliceLegend").style("display", hideZero)
        selectArcs2("path")
            .attr("d", arc2)
        selectArcs2("line")
            .attr("x1", lineX)
            .attr("x2", lineX)
            .attr("y1", lineY1)
            .attr("y2", lineY2);
        selectArcs2("text")
            .attr("transform", transformAggregatedText);
        captions.datum(data.detailed).selectAll("span.detail")
            .data(pie)
            .transition()
		    .text(function(d) { return formatNumbersThousands(d.data.value); });
    }

    return updatePie;
}

/* Insert thousand separator for better readability */
function formatNumbersThousands(value) {
    var thousandSeparator = get_format('THOUSAND_SEPARATOR');
    // Formatting with thousand separator is coming from
    // https://stackoverflow.com/a/2901298
    return value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, thousandSeparator);
}


/* ***
 * Uploads
 * *** */

/* Show uploaded file summary */
function showUploadedFileSummary(response) {
    $("#uploadedFileThumbnail").html(
        $("<img>", {
            "class" : "img-fluid",
            "src" : response.thumbnail,
            "alt" : gettext("Preview of uploaded file")
        })
    );
    $("#uploadedFilePages").text(gettext("Pages") + ": " + response.num_pages);
    $("#uploadedFileSize").text(gettext("Size") + ": " + response.size + "MB");
    $("#uploadedFileSummary").removeClass("d-none");
}


/* Configures the dropzone file upload area. We don't use the template as we want to present different information. */
$(function() {
    if(jQuery().dropzone) {
        $("#fileUploadArea").dropzone({
            addedfile : function(file) {
                $("#uploadError").addClass("d-none");
                $("#uploadProgress").removeClass("d-none");
            },
            error : function(file, response, status) {
                $("#uploadProgress").removeClass("d-none");
                var format = gettext("While uploading %(file)s the following error occured:");
                var standard_text = interpolate(format, { "file" : file["name"] }, true);
                if ("upl" in response) {
                    $("#uploadErrorText").text(standard_text + " " + response["upl"]);
                }
                else if ("message" in response) {
                    $("#uploadErrorText").text(standard_text + " " + response["message"]);
                }
                else {
                    $("#uploadErrorText").text(standard_text + " " + gettext("Unknown error"));
                }
                $("#uploadError").addClass("d-none");
            },
            headers : {
                "X-CSRFTOKEN" : getCookie("csrftoken")
            },
            paramName: "upl",
            previewsContainer: false,
            success : function(file, response) {
                // Show upload row with content
                showUploadedFileSummary(response);

                // Hide upload row and progress
                $("#fileUploadRow").addClass("d-none");
                $("#uploadProgress").addClass("d-none");

                $("#uploadFileId").val(response["file_id"])
            },
            uploadprogress: function(file, progress, bytesSent) {
                $("#uploadProgressBar").css("width", progress + "%")
            },
            url : Urls["ajax-uploadFulltext"]()
        });
    }
});

/* If the user uploads via URL, send ajax with url and show some ongoing signs */
function fileUpload() {
    var data = $("#urlForm").serialize();
    var url = Urls["ajax-downloadUrl"]();

    // Show the spinner
    $("#urlDownloadWaiter").removeClass("d-none");

    $.post(url, data)
    .done( function (response) {
        $("#uploadFileId").val(response["file_id"]);
        // Show upload row with content
        showUploadedFileSummary(response);

        // Hide upload row
        $("#fileUploadRow").addClass("d-none");
    })
    .fail( function (xhr) {
        var format = gettext("While fetching file from %(url)s the following error occured:");
        var standard_text = interpolate(format, { "url" : $("#uploadUrl").val() }, true);
        if (xhr.responseJSON) {
            if ("message" in xhr.responseJSON) {
                $("#uploadErrorText").append(
                    makeAlert(standard_text + " " + xhr.responseJSON["message"])
                );
            }
            else {
                $("#uploadErrorText").append(
                    makeAlert(standard_text + " " + gettext("Unknown error"))
                );
            }
        }
        else {
            $("#uploadErrorText").append(
                makeAlert(standard_text + " " + gettext("Unknown error"))
            );
        }
    })
    .always( function() {
        // Hide the spinner
        $("#urlDownloadWaiter").addClass("d-none");
    });
}


/* Offers option to upload another file. This is done by simply toggling the correspondings divs */
$(function() {
    $("#changeFile").click(function(evt) {
        evt.preventDefault();
        $("#uploadFileId").val("");
        $("#uploadedFileSummary").addClass("d-none");
        $("#fileUploadRow").removeClass("d-none");
    });
});

/* When radio change on documentype, collapse card and change card header */
$(function() {
    /* collapses */
    $("input[type='radio'][name='radioUploadType']").click(function(){
        $("#collapseDocType").collapse("hide");
    });

    /* changes header */
    $("#collapseDocType").on('hidden.bs.collapse', function() {
        var selected = $("input[type='radio'][name='radioUploadType']:checked");
        $("#choosenUploadType").html($("#choosenUploadType-" + selected.val()).html())
        $("#choosenUploadTypeUnfold").toggleClass("d-none");
    });
});

$(function() {
    $('#collapseDocType').on('shown.bs.collapse', function () {
        $("#choosenUploadTypeUnfold").toggleClass("d-none");
    });
});

/* When radio change on Repository, collapse card and change card header and load metadataform of the repository */
$(function() {
    /* collapses */
    $("input[type='radio'][name='radioRepository']").click(function(){
        $("#collapseRepository").collapse("hide");
        var selected = $("input[type='radio'][name='radioRepository']:checked");
        var paperPk = $("#depositForm").attr("data-paper-pk");
        $.ajax({
            data : {
                "paper" : paperPk,
                "repository" : selected.val()
            },
            error : function(xhr) {
                $("#repositoryMetadataForm").html(xhr.responseJSON["message"]);
            },
            method : "get",
            success : function(data) {
                $("#repositoryMetadataForm").html(data["form"]);
                $(".prefetchingFieldStatus").each(function(i,prefetch) {
	                initPrefetch($(prefetch));
	            });

            },
            url : Urls["ajax-get-metadata-form"]()
        });
    });

    /* changes header */
    $("#collapseRepository").on("hidden.bs.collapse", function() {
        var selected = $("input[type='radio'][name='radioRepository']:checked");
        $("#choosenRepository").html($("#choosenRepository-" + selected.val()).html())
        $("#choosenRepositoryUnfold").toggleClass("d-none");
    });
});

$(function() {
    $('#collapseRepository').on('shown.bs.collapse', function () {
        $("#choosenRepositoryUnfold").toggleClass("d-none");
    });
});

$(function() {
    $('#collapseMetadata').on('shown.bs.collapse', function () {
        $("#choosenMetadataUnfold").toggleClass("d-none");
    });
    $('#collapseMetadata').on('hidden.bs.collapse', function () {
        $("#choosenMetadataUnfold").toggleClass("d-none");
    });
});

/* This functions tries to automatically fill in some fields */
function initPrefetch(p) {
    var sorry_text = gettext("Sorry, we could not fill this for you.");
    p.text(gettext("Trying to fill this field automatically for you..."));
    field = $("#"+p.data("fieldid"));
    obj_id = $("input[name="+p.data("objfieldname")+"]").val();
    field.prop("disabled", true);

    $.ajax({
        data : {
            "field" : p.data("fieldname"),
            "id" : obj_id
        },
        error : function () {
            p.text(sorry_text);
            field.prop("disabled", false);
        },
        method : "get",
        success : function(data) {
            if(!data["success"]) {
                p.text(gettext(sorry_text));
            }
            else {
                p.text("");
            }
            field.prop("disabled", false);
            field.val(data["value"]);
        },
        url : p.data("callback")

    });
}

/* This does the actual deposit of the paper */
function depositPaper() {
    var data = $("#depositForm").serializeArray();
    var paperPk = $("#depositForm").attr("data-paper-pk");
    var no_file = gettext("You have not selected a file for upload.")

    // If no file id is present, we say, that a file is missing. Rest of the form is covered by browser and server validation
    if (!$("#uploadFileId").val()) {
        $("#errorGeneral").append(
            makeAlert(no_file)
        );
        return
    }

    // Show the waiting paper bird
    $("#paperSubmitWaitingArea").removeClass("d-none");
    $("#paperSubmitWaitingArea").addClass("d-flex");

    $.post({
        data : data,
        url : Urls["ajax-submit-deposit"](paperPk)
    })
    .done(function (response) {
        var upload_id = response["upload_id"];
        var paper_slug = $("#depositForm").attr("data-paper-slug");

        window.location.replace(Urls["paper"](paperPk, paper_slug) + "?deposit=" + upload_id);
    })
    .fail(function (xhr) {
        var error_text = "";
        if (!xhr.responseJSON) {
            error_text = gettext("Dissemin encountered an error, please try again later.");
        }
        else {
            // We have some form validation in the browser, but we do validation on the server as well and then yell back at the user depending on what is missing. Either an alert pops up or the field is going to be marked.
            var response = JSON.parse(xhr.responseText);
            if ('message' in response) {
                error_text = response["message"];
            }
            if ("form" in response) {
                form_errors = response['form'];
                if ("file_id" in form_errors) {
                    $("#errorMissingFile").append(
                        makeAlert(no_file)
                    );
                }
            }
            // This means that the metadata form is not valid. We replace it with a new one that contains the errors.
            if ("form_html" in response) {
                $("#repositoryMetadataForm").html(response["form_html"]);
            }
        }
        if (error_text) {
            $("#errorGeneral").append(
                makeAlert(error_text)
            );
        }
    })
    .always(function() {
        // Hide the waiting paper bird
        $("#paperSubmitWaitingArea").removeClass("d-flex");
        $("#paperSubmitWaitingArea").addClass("d-none");
    })
    ;
}

function makeAlert(text) {
    var alert_box = $("<div>",{
        "class" : "alert alert-warning alert-dismissible fade show uploadError",
        "role" : "alert",
        "text" : text
    }).append($("<button>", {
        "aria-label" : "Close",
        "class" : "close",
        "data-dismiss" : "alert",
        "type" : "button",
        }).append($("<span>", {
            "aria-hidden" : "true",
            "html" : "&times;"
        }))
    );

    return alert_box
};
