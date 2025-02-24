      //initialize table
      let table = new Tabulator("#equipment-state", {
        ajaxURL:ajaxURL,
        layout:"fitColumns",      //fit columns to width of table
        responsiveLayout:"hide",  //hide columns that dont fit on the table
        tooltips:true,            //show tool tips on cells
        addRowPos:"top",          //when adding a new row, add it to the top of the table
        history:true,             //allow undo and redo actions on the table
        pagination:"local",       //paginate the data
        paginationSize:10,         //allow 7 rows per page of data
        movableColumns:true,      //allow column order to be changed
        resizableRows:true,       //allow row order to be changed
        initialSort:[             //set the initial sort order of the data
            {column:"name", dir:"asc"},
        ],
        rowClick: function (e, row) {
          location = row._row.data.urlEquipmentTypeDetail
        },
        columns:[                 //define the table columns
          //{title:"id", field:"id", formatter:"number"},
          {title:"Photo", field:"pathImg", formatter:"image", formatterParams:{height: '4em'}},
          {title:"Nom", headerFilter:"input",field:"name", formatter:"link", formatterParams:{urlField:"urlEquipmentTypeDetail"}},
          {title:"Total", field:"nbTotal"},
          {title:"Indisponible", field:"nbTotalUnavailable"},
          {title:"Disponible", field:"nbTotalAvailable"},
        ],
         //create columns from data field names
      });